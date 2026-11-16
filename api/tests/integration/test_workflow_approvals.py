"""Workflow approval requests: live and late decisions, parking, continuation and fencing (AF-390)."""

from datetime import UTC, datetime, timedelta

import pytest
from hamcrest import assert_that, equal_to
from sqlmodel import Session

from api.domains.workflows.run_models import WorkflowApprovalRequest, WorkflowAttempt
from api.domains.workflows.runtime_service import WorkflowRuntimeService
from api.tests.core.givenpy import given
from api.tests.integration.test_workflow_runs import _RUN_GIVEN, attempt, start
from api.tests.integration.test_workflows import auth, base, switch_member

COMMAND = "rm -rf ./out && ./deploy.sh"


def _runtime(row, token, path="", body=None, method="POST"):
    return {
        "method": method,
        "url": f"/workflow-runtime/v1/attempts/{row.id}/approvals{path}",
        "headers": {"Authorization": f"Bearer {token}"},
        **({"json": body} if body is not None else {}),
    }


def _raise(context, row, token, command=COMMAND, **extra):
    return _report(context, row, token, command, **extra)["id"]


def _report(context, row, token, command=COMMAND, **extra):
    response = context.client.request(
        **_runtime(row, token, body={"command": command, "runtime_run_id": "hermes-run-1", **extra})
    )
    assert_that(response.status_code, equal_to(200), response.text)
    return response.json()


def _set(context, model, row_id, **values):
    with Session(context.postgres_delegate.engine) as session:
        stored = session.get_one(model, row_id)
        for key, value in values.items():
            setattr(stored, key, value)
        session.add(stored)
        session.commit()


def _expires_at(context, row):
    with Session(context.postgres_delegate.engine) as session:
        return session.get_one(WorkflowAttempt, row.id).expires_at


def _status(context, row, token, request_id, path=""):
    method = "GET" if not path else "POST"
    return context.client.request(**_runtime(row, token, f"/{request_id}{path}", {} if path else None, method))


def _run(context, run_id):
    return context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()


def _decide(context, run_id, request_id, decision, guidance=None):
    return context.client.post(
        base(context) + f"/workflow-runs/{run_id}/approvals/{request_id}/decision",
        headers=auth(context),
        json={"decision": decision, **({"guidance": guidance} if guidance else {})},
    )


def _started(context):
    response, _, _ = start(context)
    return attempt(context, response.json()["id"])


def test_a_live_request_is_shown_exactly_and_waiting_does_not_consume_the_attempt() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        # The request arrives 50 seconds before the step's deadline.
        _set(context, WorkflowAttempt, row.id, expires_at=datetime.now(UTC) + timedelta(seconds=50))
        request_id = _raise(context, row, token)
        run = _run(context, row.run_id)
        assert_that(
            (run["state"], run["approval"]["command"], run["approval"]["state"], run["allowed_actions"]),
            equal_to(("RUNNING", COMMAND, "LIVE", ["decide", "cancel"])),
        )
        assert _expires_at(context, row) > datetime.now(UTC) + timedelta(seconds=270 + 50)
        # Approved after waiting about 200 seconds: the step keeps its own 50 seconds plus the wait.
        waited = timedelta(seconds=200)
        with Session(context.postgres_delegate.engine) as session:
            request = session.get_one(WorkflowApprovalRequest, request_id)
            _set(context, WorkflowApprovalRequest, request_id, live_until=request.live_until - waited)
        _set(context, WorkflowAttempt, row.id, expires_at=_expires_at(context, row) - waited)
        _decide(context, row.run_id, request_id, "approve")
        remaining = (_expires_at(context, row) - datetime.now(UTC)).total_seconds()
        assert 50 + 60 - 5 <= remaining <= 50 + 60 + 5, remaining


def test_a_retried_report_is_the_same_request_with_only_the_time_left() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        first = _report(context, row, token)
        assert 265 <= first["live_seconds"] <= 270
        _set(context, WorkflowApprovalRequest, first["id"], live_until=datetime.now(UTC) + timedelta(seconds=240))
        _decide(context, row.run_id, first["id"], "approve")
        # The first response was lost; the retry lands after the decision and must not ask again.
        retried = _report(context, row, token)
        assert_that(retried["id"], equal_to(first["id"]))
        assert 230 <= retried["live_seconds"] <= 240
        assert_that(len(_run(context, row.run_id)["approvals"]), equal_to(1))
        assert_that(_status(context, row, token, first["id"]).json(), equal_to({"state": "APPROVED"}))


def test_the_live_window_counts_from_when_the_runtime_raised_the_request() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        raised = _report(context, row, token, age_seconds=40)
        assert 225 <= raised["live_seconds"] <= 230


def test_a_live_request_past_its_window_is_no_longer_offered_for_a_decision() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _set(context, WorkflowApprovalRequest, request_id, live_until=datetime.now(UTC) - timedelta(seconds=1))
        run = _run(context, row.run_id)
        assert_that((run["approval"]["state"], run["allowed_actions"]), equal_to(("LIVE", ["cancel"])))
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(409))


def test_a_live_approval_is_released_once_and_recorded_with_its_decider() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        decided = _decide(context, row.run_id, request_id, "approve")
        assert_that(decided.status_code, equal_to(200), decided.text)
        assert_that(decided.json()["approval"]["decided_by_user_id"], equal_to(str(context.user.id)))
        assert_that(_status(context, row, token, request_id).json(), equal_to({"state": "APPROVED"}))
        assert_that(_status(context, row, token, request_id, "/released").status_code, equal_to(204))
        assert_that(_run(context, row.run_id)["approval"]["state"], equal_to("RELEASED"))
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(409))


def test_a_live_decline_carries_the_verbatim_guidance_back_to_the_session() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _decide(context, row.run_id, request_id, "decline", "Write to ./tmp, never ./out")
        status = _status(context, row, token, request_id).json()
        assert_that(status["state"], equal_to("DECLINED"))
        assert "Write to ./tmp, never ./out" in status["prompt"] and "Do not run it" in status["prompt"]
        assert_that(_run(context, row.run_id)["state"], equal_to("RUNNING"))


def test_an_unanswered_request_parks_and_a_late_approval_continues_the_same_session() -> None:
    with given(_RUN_GIVEN) as context:
        repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        parked = _status(context, row, token, request_id, "/park")
        assert_that(parked.json(), equal_to({"state": "PARKED"}))
        run = _run(context, row.run_id)
        assert_that((run["state"], run["allowed_actions"]), equal_to(("AWAITING_APPROVAL", ["decide", "cancel"])))
        assert_that(_decide(context, row.run_id, request_id, "approve").json()["state"], equal_to("QUEUED"))
        continued, _ = repository.advance(row.run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(continued.id, repository.token(continued.id))
        assert_that((handoff["session_id"], handoff["resume"]), equal_to((f"workflow-{row.id}", True)))
        assert "approved" in handoff["prompt"] and COMMAND in handoff["prompt"]
        # The Agent asks again in the continued session: a new live request in the original session.
        again = _raise(context, continued, repository.token(continued.id))
        assert again != request_id
        assert_that(_run(context, row.run_id)["approval"]["state"], equal_to("LIVE"))


def test_a_decision_that_arrives_before_the_window_closes_wins_the_park() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _decide(context, row.run_id, request_id, "approve")
        assert_that(_status(context, row, token, request_id, "/park").json(), equal_to({"state": "APPROVED"}))
        assert_that(_run(context, row.run_id)["state"], equal_to("RUNNING"))


def test_repeated_declines_block_the_step_and_fence_the_session() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        for number in range(3):
            request_id = _raise(context, row, token, f"{COMMAND} #{number}")
            _decide(context, row.run_id, request_id, "decline", "No")
            if number < 2:
                _status(context, row, token, request_id)
        run = _run(context, row.run_id)
        assert_that((run["state"], run["allowed_actions"]), equal_to(("BLOCKED", ["cancel"])))
        assert_that(_status(context, row, token, request_id).status_code, equal_to(409))


def _expire(context, row):
    with Session(context.postgres_delegate.engine) as session:
        stored = session.get_one(WorkflowAttempt, row.id)
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(stored)
        session.commit()


def test_an_attempt_that_expires_with_a_request_unanswered_blocks_as_uncertain() -> None:
    with given(_RUN_GIVEN) as context:
        repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _expire(context, row)
        repository.advance(row.run_id)
        repository.advance(row.run_id, stopped=True)
        run = _run(context, row.run_id)
        # Hermes may have denied the command itself and carried on; nothing proves it did not.
        assert_that((run["state"], run["approval"]["state"]), equal_to(("BLOCKED", "LAPSED")))
        assert "uncertain" in run["reason"]
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(409))


def _agent_status(context, status):
    from api.domains.agents.models import Agent

    _set(context, Agent, context.agent.id, status=status)


def _parked(context):
    repository, row, token = _started(context)
    request_id = _raise(context, row, token)
    _status(context, row, token, request_id, "/park")
    return repository, row, request_id


def test_a_parked_request_survives_an_agent_stop_and_continues_after_restart() -> None:
    from api.domains.agents.models import AgentStatus

    with given(_RUN_GIVEN) as context:
        repository, row, request_id = _parked(context)
        _agent_status(context, AgentStatus.STOPPED)  # e.g. a managed update's backup
        repository.advance(row.run_id)
        run = _run(context, row.run_id)
        assert_that((run["state"], run["approval"]["state"]), equal_to(("AWAITING_APPROVAL", "PARKED")))
        # Deciding while the Agent is stopped records the decision; the session continues later.
        assert_that(_decide(context, row.run_id, request_id, "approve").json()["state"], equal_to("AWAITING_APPROVAL"))
        continued, _ = repository.advance(row.run_id)
        assert continued is None
        _agent_status(context, AgentStatus.RUNNING)
        continued, _ = repository.advance(row.run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(continued.id, repository.token(continued.id))
        assert_that((handoff["session_id"], handoff["resume"]), equal_to((f"workflow-{row.id}", True)))
        history = context.client.get(
            base(context) + f"/workflow-runs/{row.run_id}/history?page_size=100", headers=auth(context)
        ).json()["items"]
        assert any("continued in its previous session" in item["detail"] for item in history)


def test_a_decider_who_lost_access_before_the_continuation_must_be_replaced() -> None:
    with given(_RUN_GIVEN) as context:
        repository, row, request_id = _parked(context)
        _decide(context, row.run_id, request_id, "approve")
        # The decider's membership is gone by the time the continuation would start.
        _set(context, WorkflowApprovalRequest, request_id, decided_by_user_id=None)
        continued, _ = repository.advance(row.run_id)
        assert continued is None
        run = _run(context, row.run_id)
        assert_that(
            (run["state"], run["approval"]["state"], run["allowed_actions"]),
            equal_to(("AWAITING_APPROVAL", "PARKED", ["decide", "cancel"])),
        )
        assert "decide again" in run["reason"]
        # A fresh decision by someone with access continues the step.
        _decide(context, row.run_id, request_id, "approve")
        continued, _ = repository.advance(row.run_id)
        assert continued is not None


def test_an_approval_the_runtime_never_confirmed_blocks_as_uncertain() -> None:
    with given(_RUN_GIVEN) as context:
        repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _decide(context, row.run_id, request_id, "approve")
        _expire(context, row)
        repository.advance(row.run_id)
        repository.advance(row.run_id, stopped=True)
        run = _run(context, row.run_id)
        assert_that((run["state"], run["allowed_actions"]), equal_to(("BLOCKED", ["cancel"])))
        assert "uncertain" in run["reason"]


def test_cancelling_a_parked_run_lapses_its_request() -> None:
    with given(_RUN_GIVEN) as context:
        repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _status(context, row, token, request_id, "/park")
        run = _run(context, row.run_id)
        context.client.post(
            base(context) + f"/workflow-runs/{row.run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": run["revision"]},
        )
        repository.advance(row.run_id)
        run = _run(context, row.run_id)
        assert_that((run["state"], run["approval"]["state"]), equal_to(("CANCELLED", "LAPSED")))
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(409))


def test_a_viewer_sees_the_request_but_cannot_decide() -> None:
    from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
    from api.tests.steps.agent import there_is_agent_access

    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        switch_member(context)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        run = _run(context, row.run_id)
        assert_that((run["approval"]["command"], run["allowed_actions"]), equal_to((COMMAND, [])))
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(403))


def test_a_forged_capability_cannot_raise_or_read_a_request() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        assert_that(_status(context, row, "forged", request_id).status_code, equal_to(409))
        assert_that(
            context.client.request(
                **_runtime(row, "forged", body={"command": "ls", "runtime_run_id": "x"})
            ).status_code,
            equal_to(409),
        )


def test_the_inbox_lists_only_runs_awaiting_a_decision_with_their_request() -> None:
    with given(_RUN_GIVEN) as context:
        _, waiting, token = _started(context)
        request_id = _raise(context, waiting, token)
        start(context)  # another run with nothing to decide
        listed = context.client.get(
            base(context) + "/workflow-runs?awaiting_decision=true&page_size=1", headers=auth(context)
        ).json()
        assert_that(listed["total"], equal_to(1))
        assert_that(
            (listed["items"][0]["id"], listed["items"][0]["approval"]["id"]),
            equal_to((str(waiting.run_id), request_id)),
        )
        everything = context.client.get(base(context) + "/workflow-runs", headers=auth(context)).json()
        assert_that(everything["total"], equal_to(2))
        _decide(context, waiting.run_id, request_id, "approve")
        after = context.client.get(
            base(context) + "/workflow-runs?awaiting_decision=true", headers=auth(context)
        ).json()
        assert_that(after["total"], equal_to(0))


def test_the_run_keeps_every_decision_with_its_decider_and_guidance() -> None:
    with given(_RUN_GIVEN) as context:
        _, row, token = _started(context)
        first = _raise(context, row, token, "mkdir -p /tmp/af390")
        _decide(context, row.run_id, first, "approve")
        _status(context, row, token, first, "/released")
        second = _raise(context, row, token)
        _decide(context, row.run_id, second, "decline", "List the folder instead")
        approvals = _run(context, row.run_id)["approvals"]
        assert_that(
            [(item["command"], item["state"], item["guidance"]) for item in approvals],
            equal_to([("mkdir -p /tmp/af390", "RELEASED", None), (COMMAND, "DECLINED", "List the folder instead")]),
        )
        assert_that({item["decided_by_user_id"] for item in approvals}, equal_to({str(context.user.id)}))


@pytest.mark.parametrize("retryable", [False, True])
def test_a_failed_run_closes_its_open_request_and_leaves_the_inbox(retryable) -> None:
    with given(_RUN_GIVEN) as context:
        _, row, token = _started(context)
        request_id = _raise(context, row, token)
        failed = context.client.post(
            f"/workflow-runtime/v1/attempts/{row.id}/failure",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "The Agent session ended", "retryable": retryable},
        )
        assert_that(failed.status_code, equal_to(204))
        run = _run(context, row.run_id)
        assert_that(
            (run["state"], run["approval"]["state"], run["allowed_actions"]),
            equal_to(("BLOCKED" if retryable else "FAILED", "LAPSED", ["cancel"] if retryable else ["rerun"])),
        )
        inbox = context.client.get(
            base(context) + "/workflow-runs?awaiting_decision=true", headers=auth(context)
        ).json()
        assert_that(inbox["total"], equal_to(0))
        assert_that(_decide(context, row.run_id, request_id, "approve").status_code, equal_to(409))


def test_retention_removes_approval_commands_and_guidance() -> None:
    from api.domains.workflows.run_models import WorkflowApprovalRequest, WorkflowRun

    with given(_RUN_GIVEN) as context:
        repository, row, token = _started(context)
        request_id = _raise(context, row, token)
        _decide(context, row.run_id, request_id, "decline", "Use the staging bucket instead")
        run = _run(context, row.run_id)
        context.client.post(
            base(context) + f"/workflow-runs/{row.run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": run["revision"]},
        )
        repository.advance(row.run_id)
        repository.advance(row.run_id, stopped=True)
        with Session(context.postgres_delegate.engine) as session:
            stored = session.get_one(WorkflowRun, row.run_id)
            assert stored.settled_at is not None
            stored.settled_at = datetime.now(UTC) - timedelta(days=91)
            session.add(stored)
            session.commit()
        repository.expire_content()
        approval = _run(context, row.run_id)["approvals"][0]
        assert COMMAND not in approval["command"]
        assert_that(approval["guidance"], equal_to(None))
        assert_that(approval["decided_by_user_id"], equal_to(str(context.user.id)))
        with Session(context.postgres_delegate.engine) as session:
            stored_request = session.get_one(WorkflowApprovalRequest, request_id)
            assert COMMAND not in stored_request.command
            assert stored_request.command_sha256 == ""
