"""Approval steps: a run waits for a person, who approves, requests changes to the step before, or rejects.

Deciding requires `agent.update` on the run's Agent at decision time, as for command approvals; per
docs/features/rbac/IMPLEMENTATION-BRIEF.md a concealed Agent answers 404 and a visible one without the
operation answers 403.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length, is_not
from sqlmodel import Session, col, select

from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.workflows import config as workflow_config
from api.domains.workflows.models import WorkflowVersion
from api.domains.workflows.run_models import AttemptResult, WorkflowCheckpoint, WorkflowRun, WorkflowStepApproval
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.domains.workflows.runtime_service import REVISION_INSTRUCTIONS, WorkflowRuntimeService
from api.tests.core.givenpy import given
from api.tests.integration.test_workflow_approvals import _decide as _decide_command
from api.tests.integration.test_workflow_approvals import _raise as _raise_command
from api.tests.integration.test_workflow_runs import _RUN_GIVEN, attempt, start
from api.tests.integration.test_workflows import auth, base, post_draft, switch_member
from api.tests.steps.agent import there_is_agent_access


def _step(name: str, goal: str, kind: str = "agent") -> dict:
    return {"id": str(uuid4()), "name": name, "goal": goal, **({"type": kind} if kind != "agent" else {})}


def _body(*steps: dict) -> dict:
    return {
        "name": "Reviewed report",
        "steps": list(steps),
        "inputs": [
            {"key": "period", "label": "Reporting period", "description": "The period", "type": "text"},
        ],
    }


DRAFT = _step("Draft", "Write the report")
REVIEW = _step("Review the draft", "Check the tone and the numbers", "approval")
PUBLISH = _step("Publish", "Publish the approved report")


def _saved(context, *steps: dict) -> dict:
    response = post_draft(context, _body(*steps))
    assert_that(response.status_code, equal_to(201), response.text)
    return response.json()


def _run_url(context, run_id: str) -> str:
    return base(context) + f"/workflow-runs/{run_id}"


def _run(context, run_id: str, headers=None) -> dict:
    return context.client.get(_run_url(context, run_id), headers=headers or auth(context)).json()


def _complete(context, run_id: str, summary: str) -> tuple:
    repository, row, token = attempt(context, run_id)
    repository.complete(row.id, token, AttemptResult(summary=summary, criteria_met=True))
    return row, token


def _decide(context, run_id: str, approval_id: str, decision: str, note: str | None = None, headers=None):
    return context.client.post(
        _run_url(context, run_id) + f"/step-approvals/{approval_id}/decision",
        headers=headers or auth(context),
        json={"decision": decision, **({"note": note} if note is not None else {})},
    )


def _waiting_run(context, *steps: dict) -> dict:
    """A run whose first step completed, now waiting at the Approval step after it."""
    response, _, _ = start(context, _saved(context, *steps))
    assert_that(response.status_code, equal_to(202), response.text)
    run_id = response.json()["id"]
    _complete(context, run_id, "First draft")
    return _run(context, run_id)


def _history(context, run_id: str) -> list[str]:
    items = context.client.get(_run_url(context, run_id) + "/history?page_size=100", headers=auth(context)).json()
    return [item["kind"] for item in items["items"]]


# --- Authoring -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([REVIEW, DRAFT], "Step 1 is an Approval step"),
        ([DRAFT, REVIEW, {**REVIEW, "id": str(uuid4())}], "Steps 2 and 3 are both Approval steps"),
        ([DRAFT, {**REVIEW, "completion_criteria": "Tone is right"}], "has only its instructions"),
        ([DRAFT, {**REVIEW, "allowed_decisions": ["reject"]}], "always allows Approve"),
        ([{**DRAFT, "allowed_decisions": ["approve"]}, REVIEW], "Only an Approval step has allowed decisions"),
    ],
    ids=["first", "consecutive", "with-criteria", "without-approve", "on-agent-step"],
)
def test_an_approval_step_must_follow_an_agent_step_and_has_only_instructions(steps, message) -> None:
    with given(_RUN_GIVEN) as context:
        response = post_draft(context, _body(*steps))
        assert_that(response.status_code, equal_to(422))
        assert_that(response.text, contains_string(message))


def test_agent_steps_are_stored_as_before_and_approval_steps_with_their_type() -> None:
    with given(_RUN_GIVEN) as context:
        saved = _saved(context, DRAFT, REVIEW)
        assert_that([step["type"] for step in saved["version"]["draft"]["steps"]], equal_to(["agent", "approval"]))
        with Session(context.postgres_delegate.engine) as session:
            stored = session.get_one(WorkflowVersion, UUID(saved["version"]["id"])).snapshot["steps"]
        # An API that predates Approval steps can still read a version made only of Agent steps.
        assert_that(["type" in step for step in stored], equal_to([False, True]))
        assert_that("allowed_decisions" in stored[0], equal_to(False))
        # Without a choice, an Approval step offers every decision.
        assert_that(stored[1]["allowed_decisions"], equal_to(["approve", "request_changes", "reject"]))


def test_allowed_decisions_are_stored_in_order_and_only_those_can_be_made() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, {**REVIEW, "allowed_decisions": ["reject", "approve"]})
        assert_that(run["steps"][1]["allowed_decisions"], equal_to(["approve", "reject"]))
        assert_that(run["steps"][0]["allowed_decisions"], equal_to(None))
        response = _decide(context, run["id"], run["step_approval"]["id"], "request_changes", "Shorter")
        assert_that(response.status_code, equal_to(422))
        assert_that(response.json()["detail"], equal_to("This approval step allows only approve, reject"))
        assert_that(_run(context, run["id"])["step_approval"]["state"], equal_to("WAITING"))
        assert_that(_decide(context, run["id"], run["step_approval"]["id"], "reject").status_code, equal_to(200))


# --- Waiting and approving -------------------------------------------------------------------------------------


def test_a_run_waits_at_an_approval_step_and_shows_in_the_approvals_inbox() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        assert_that((run["state"], run["next_step"]), equal_to(("AWAITING_APPROVAL", 1)))
        assert_that([step["state"] for step in run["steps"]], equal_to(["COMPLETED", "WAITING", "PENDING"]))
        assert_that(run["steps"][1]["type"], equal_to("approval"))
        assert_that(
            (run["steps"][0]["instructions"], run["steps"][1]["instructions"]),
            equal_to((None, "Check the tone and the numbers")),
        )
        assert_that((run["step_approval"]["round"], run["step_approval"]["state"]), equal_to((1, "WAITING")))
        assert_that(run["allowed_actions"], equal_to(["decide_step", "cancel"]))
        assert_that(run["reason"], equal_to("Waiting for approval at step 2: Review the draft"))
        # The step's completion is recorded before the run starts waiting.
        assert_that(_history(context, run["id"])[-2:], equal_to(["STEP_COMPLETED", "APPROVAL_STEP_WAITING"]))
        # Nothing is sent to the Agent while the run waits.
        assert_that(context.injector.get(WorkflowRunRepository).advance(UUID(run["id"]))[0], equal_to(None))
        inbox = context.client.get(
            base(context) + "/workflow-runs?awaiting_decision=true", headers=auth(context)
        ).json()
        assert_that([item["id"] for item in inbox["items"]], equal_to([run["id"]]))
        assert_that(inbox["items"][0]["step_approval"]["id"], equal_to(run["step_approval"]["id"]))


def test_approving_continues_with_the_next_step_which_sees_the_approval() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        response = _decide(context, run["id"], run["step_approval"]["id"], "approve", "Numbers checked")
        assert_that(response.status_code, equal_to(200), response.text)
        decided = response.json()
        assert_that((decided["state"], decided["next_step"]), equal_to(("QUEUED", 2)))
        assert_that(decided["step_approvals"][0]["decided_by_user_id"], equal_to(str(context.user.id)))
        assert_that(decided["steps"][1]["summary"], contains_string("Numbers checked"))

        repository, row, token = attempt(context, run["id"])
        packet = context.injector.get(WorkflowRuntimeService).handoff(row.id, token)["prompt"]
        assert_that(
            packet, contains_string("A person approved the previous step's result. Their note: Numbers checked")
        )
        assert_that(packet, is_not(contains_string("revision_request")))
        repository.complete(row.id, token, AttemptResult(summary="Published", criteria_met=True))
        finished = _run(context, run["id"])
        assert_that((finished["state"], finished["final_summary"]), equal_to(("SUCCEEDED", "Published")))


def test_an_approval_step_can_end_the_workflow_and_the_result_is_the_step_it_approved() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        response = _decide(context, run["id"], run["step_approval"]["id"], "approve")
        finished = response.json()
        assert_that((finished["state"], finished["final_summary"]), equal_to(("SUCCEEDED", "First draft")))
        assert_that(finished["settled_at"], is_not(None))


# --- Requesting changes ----------------------------------------------------------------------------------------


def test_requesting_changes_needs_notes() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        for note in (None, "   "):
            response = _decide(context, run["id"], run["step_approval"]["id"], "request_changes", note)
            assert_that(response.status_code, equal_to(422))
        assert_that(_run(context, run["id"])["step_approval"]["state"], equal_to("WAITING"))


def test_requesting_changes_reruns_the_step_before_with_the_notes_then_asks_again() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        first_round = run["step_approval"]["id"]
        response = _decide(context, run["id"], first_round, "request_changes", "Shorten the intro")
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that((response.json()["state"], response.json()["next_step"]), equal_to(("QUEUED", 0)))
        assert_that(_history(context, run["id"])[-1], equal_to("CHANGES_REQUESTED"))

        # The step runs again in a fresh session that knows what to change and what it produced before.
        repository, row, token = attempt(context, run["id"])
        handoff = context.injector.get(WorkflowRuntimeService).handoff(row.id, token)
        assert_that(handoff["resume"], equal_to(False))
        assert_that(handoff["prompt"], contains_string(REVISION_INSTRUCTIONS))
        assert_that(handoff["prompt"], contains_string('"notes": "Shorten the intro"'))
        assert_that(handoff["prompt"], contains_string('"summary": "First draft"'))
        repository.complete(row.id, token, AttemptResult(summary="Second draft", criteria_met=True))

        again = _run(context, run["id"])
        assert_that((again["state"], again["step_approval"]["round"]), equal_to(("AWAITING_APPROVAL", 2)))
        assert_that((again["steps"][0]["summary"], again["steps"][0]["round"]), equal_to(("Second draft", 2)))
        # The result sent back stays readable as an earlier round of the step.
        assert_that(
            [(item["round"], item["summary"]) for item in again["steps"][0]["earlier_rounds"]],
            equal_to([(1, "First draft")]),
        )
        assert_that(
            [(item["round"], item["state"], item["note"]) for item in again["step_approvals"]],
            equal_to([(1, "CHANGES_REQUESTED", "Shorten the intro"), (2, "WAITING", None)]),
        )
        # A decision on the earlier round is stale.
        assert_that(_decide(context, run["id"], first_round, "approve").status_code, equal_to(409))
        with Session(context.postgres_delegate.engine) as session:
            rounds = session.exec(
                select(WorkflowCheckpoint)
                .where(col(WorkflowCheckpoint.run_id) == UUID(run["id"]))
                .order_by(col(WorkflowCheckpoint.round))
            ).all()
            assert_that(
                [(item.round, item.superseded_at is not None, item.result["summary"]) for item in rounds],
                equal_to([(1, True, "First draft"), (2, False, "Second draft")]),
            )

        _decide(context, run["id"], again["step_approval"]["id"], "approve")
        repository, row, token = attempt(context, run["id"])
        packet = context.injector.get(WorkflowRuntimeService).handoff(row.id, token)["prompt"]
        # Later steps see only the current round of the step that ran again.
        assert_that(packet, contains_string("Second draft"))
        assert_that(packet, is_not(contains_string("First draft")))


def test_a_step_run_again_does_not_continue_a_command_decided_in_its_earlier_round() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context, _saved(context, DRAFT, REVIEW, PUBLISH))
        run_id = response.json()["id"]
        repository, row, token = attempt(context, run_id)
        request_id = _raise_command(context, row, token)
        # Approved while live; the step then finishes without the runtime confirming the release.
        assert_that(_decide_command(context, run_id, request_id, "approve").status_code, equal_to(200))
        repository.complete(row.id, token, AttemptResult(summary="First draft", criteria_met=True))
        waiting = _run(context, run_id)["step_approval"]
        _decide(context, run_id, waiting["id"], "request_changes", "Shorten the intro")

        repository, row, token = attempt(context, run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(row.id, token)
        # A fresh session with the notes, not the earlier round's session told to run the command again.
        assert_that(handoff["resume"], equal_to(False))
        assert_that(handoff["prompt"], contains_string(REVISION_INSTRUCTIONS))
        assert_that(handoff["prompt"], is_not(contains_string('"continuation"')))
        assert_that(_history(context, run_id)[-1], equal_to("ATTEMPT_STARTED"))
        assert_that(_run(context, run_id)["state"], equal_to("RUNNING"))


# --- Rejecting -------------------------------------------------------------------------------------------------


def test_rejecting_settles_the_run_as_rejected_with_the_reason() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        response = _decide(context, run["id"], run["step_approval"]["id"], "reject", "Wrong quarter")
        rejected = response.json()
        assert_that(
            (rejected["state"], rejected["reason"], rejected["steps"][1]["state"]),
            equal_to(("REJECTED", "Rejected at step 2: Wrong quarter", "REJECTED")),
        )
        assert_that(rejected["settled_at"], is_not(None))
        # The Approval step ended with the decision, so its time is known.
        assert_that(rejected["steps"][1]["completed_at"], is_not(None))
        # A rejected run is settled, so it can be run again like any other finished run.
        assert_that(rejected["allowed_actions"], equal_to(["rerun"]))
        settled = context.client.get(base(context) + "/workflow-runs?status=settled", headers=auth(context)).json()
        assert_that([item["id"] for item in settled["items"]], equal_to([run["id"]]))
        assert_that(_decide(context, run["id"], run["step_approval"]["id"], "approve").status_code, equal_to(409))


def test_expiring_a_rejected_runs_content_removes_the_note_from_its_reason() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        _decide(context, run["id"], run["step_approval"]["id"], "reject", "Wrong quarter")
        with Session(context.postgres_delegate.engine) as session:
            stored = session.get_one(WorkflowRun, UUID(run["id"]))
            stored.settled_at = datetime.now(UTC) - timedelta(days=workflow_config.HISTORY_RETENTION_DAYS + 1)
            session.add(stored)
            session.commit()
        context.injector.get(WorkflowRunRepository).expire_content()
        expired = _run(context, run["id"])
        assert_that(expired["reason"], equal_to("Rejected at step 2"))
        assert_that([item["note"] for item in expired["step_approvals"]], equal_to([None]))


# --- Fencing ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("decisions", [["approve", "reject"], ["reject", "request_changes"]])
def test_concurrent_decisions_record_exactly_one(decisions) -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)

        def decide(decision):
            return _decide(context, run["id"], run["step_approval"]["id"], decision, "note").status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(decide, decisions))
        assert_that(statuses, equal_to([200, 409]))
        with Session(context.postgres_delegate.engine) as session:
            states = session.exec(select(WorkflowStepApproval.state)).all()
        assert_that(states, has_length(1))


def test_cancelling_a_waiting_run_closes_its_approval_step() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW, PUBLISH)
        response = context.client.post(
            _run_url(context, run["id"]) + "/cancel", headers=auth(context), json={"expected_revision": run["revision"]}
        )
        assert_that(response.status_code, equal_to(200), response.text)
        context.injector.get(WorkflowRunRepository).advance(UUID(run["id"]))
        cancelled = _run(context, run["id"])
        assert_that(cancelled["state"], equal_to("CANCELLED"))
        assert_that(cancelled["step_approvals"][0]["state"], equal_to("LAPSED"))
        assert_that(_decide(context, run["id"], run["step_approval"]["id"], "approve").status_code, equal_to(409))


def test_a_deleted_agents_waiting_run_is_cancelled_and_cannot_be_decided() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        context.agent.deleted_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(_decide(context, run["id"], run["step_approval"]["id"], "approve").status_code, equal_to(409))
        context.injector.get(WorkflowRunRepository).advance(UUID(run["id"]))
        assert_that(_run(context, run["id"])["step_approvals"][0]["state"], equal_to("LAPSED"))


def test_an_approval_of_another_run_cannot_be_decided_through_this_run() -> None:
    with given(_RUN_GIVEN) as context:
        first = _waiting_run(context, DRAFT, REVIEW)
        second = _waiting_run(context, DRAFT, REVIEW)
        response = _decide(context, first["id"], second["step_approval"]["id"], "approve")
        assert_that(response.status_code, equal_to(409))
        assert_that(_run(context, second["id"])["step_approval"]["state"], equal_to("WAITING"))


# --- Authority -------------------------------------------------------------------------------------------------


def _as_member(context, role_id=None) -> dict:
    """A new Member's headers, optionally with explicit access to the Agent; the context stays the Owner's."""
    owner = (context.user, context.access_token)
    switch_member(context)
    if role_id is not None:
        there_is_agent_access(access_role_id=role_id)(context)
    headers, member = auth(context), context.user
    context.user, context.access_token = owner
    return {"headers": headers, "user": member}


@pytest.mark.parametrize(
    ("role_id", "status"),
    [(AGENT_EDITOR_ROLE_ID, 200), (AGENT_VIEWER_ROLE_ID, 403), (None, 404)],
    ids=["agent-editor", "agent-viewer", "no-agent-access"],
)
def test_deciding_needs_agent_update_on_the_runs_agent(role_id, status) -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        member = _as_member(context, role_id)
        response = _decide(context, run["id"], run["step_approval"]["id"], "approve", headers=member["headers"])
        assert_that(response.status_code, equal_to(status), response.text)
        decided = _run(context, run["id"])["step_approvals"][0]
        if status == 200:
            assert_that(decided["decided_by_user_id"], equal_to(str(member["user"].id)))
        else:
            assert_that(decided["state"], equal_to("WAITING"))


def test_a_viewer_sees_the_waiting_approval_step_without_the_decide_action() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        member = _as_member(context, AGENT_VIEWER_ROLE_ID)
        seen = _run(context, run["id"], headers=member["headers"])
        assert_that((seen["step_approval"]["state"], seen["allowed_actions"]), equal_to(("WAITING", [])))
