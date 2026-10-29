from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, equal_to, has_length, is_
from sqlalchemy import text
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.events.models import EventDelivery, OutboxMessage
from api.domains.rbac.policy import AuthorizationScope
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_models import AttemptResult, WorkflowCheckpoint, WorkflowRun, WorkflowRunCreate
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.domains.workflows.run_service import WorkflowRunService
from api.domains.workflows.runtime_service import WorkflowRuntimeService
from api.tests.core.givenpy import given
from api.tests.integration.test_workflows import _GIVEN, auth, base, create, switch_member

_RUN_GIVEN = _GIVEN


def start(context, saved=None, **changes):
    context.agent.status = AgentStatus.RUNNING
    context.injector.get(AgentRepository).save(context.agent)
    saved = saved or create(context)
    payload = {
        "version_id": saved["version"]["id"],
        "client_request_id": str(uuid4()),
        "inputs": {"period": "This week"},
        **changes,
    }
    response = context.client.post(
        base(context) + f"/workflows/{saved['id']}/runs", headers=auth(context), json=payload
    )
    return response, saved, payload


def attempt(context, run_id):
    repository = context.injector.get(WorkflowRunRepository)
    row, _ = repository.advance(UUID(run_id))
    assert_that(row is not None, is_(True))
    return repository, row, repository.token(row.id)


def result():
    return AttemptResult(
        summary="Summary prepared from supplied inputs",
        criteria_met=True,
    )


def test_start_pins_version_inputs_actor_and_transactional_wakeup() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        assert_that(response.status_code, equal_to(202), response.text)
        run = response.json()
        assert_that(
            (run["version_id"], run["inputs"], run["initiating_user_id"]),
            equal_to((saved["version"]["id"], {"period": "This week"}, str(context.user.id))),
        )
        with Session(context.postgres_delegate.engine) as session:
            event = session.exec(select(OutboxMessage).where(OutboxMessage.event_name == "workflow.run.changed")).one()
            deliveries = session.exec(select(EventDelivery).where(EventDelivery.event_id == event.event_id)).all()
            assert_that(deliveries, has_length(1))
        history = context.client.get(
            base(context) + f"/workflow-runs/{run['id']}/history", headers=auth(context)
        ).json()
        assert_that(history["total"], equal_to(1))
        assert_that(history["items"][0]["detail"], equal_to("Run started using version 1"))


def test_duplicate_start_is_stable_and_conflicting_reuse_is_rejected() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, payload = start(context)
        path = base(context) + f"/workflows/{saved['id']}/runs"
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicates = list(
                pool.map(lambda _: context.client.post(path, headers=auth(context), json=payload), range(2))
            )
        assert_that([r.json()["id"] for r in duplicates], equal_to([response.json()["id"]] * 2))
        payload["inputs"] = {"period": "Different week"}
        assert_that(context.client.post(path, headers=auth(context), json=payload).status_code, equal_to(409))


@pytest.mark.parametrize("inputs", [{}, {"period": True}, {"period": 123}, {"other": "value"}])
def test_invalid_inputs_do_not_queue_work(inputs) -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context, inputs=inputs)
        assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("capability", ["business_action", "native_command"])
def test_declared_capabilities_do_not_gate_execution(capability) -> None:
    """Steps run under the Agent's own tools, integrations and approval mode."""
    from api.tests.helpers.workflows import draft

    with given(_RUN_GIVEN) as context:
        body = draft()
        body["steps"][0]["required_capabilities"] = [capability]
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
        response, _, _ = start(context, saved)
        assert_that(response.status_code, equal_to(202), response.text)


def test_multiple_active_runs_are_accepted_for_one_workflow() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        run_ids = []
        for _ in range(4):
            response, _, _ = start(context, saved)
            assert_that(response.status_code, equal_to(202), response.text)
            run_ids.append(UUID(response.json()["id"]))
        with Session(context.postgres_delegate.engine) as session:
            runs = session.exec(select(WorkflowRun).where(col(WorkflowRun.id).in_(run_ids))).all()
            assert_that(runs, has_length(4))
            assert_that([run.state for run in runs], equal_to(["QUEUED"] * 4))


def test_concurrent_starts_are_accepted_across_an_agents_workflows() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        assert_that(response.status_code, equal_to(202))
        definitions = [create(context), create(context)]

        def submit(saved):
            return context.client.post(
                base(context) + f"/workflows/{saved['id']}/runs",
                headers=auth(context),
                json={
                    "version_id": saved["version"]["id"],
                    "client_request_id": str(uuid4()),
                    "inputs": {"period": "This week"},
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, definitions))
        assert_that([response.status_code for response in responses], equal_to([202, 202]))


def test_cancel_fences_current_attempt_before_quiescence() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        current = context.client.get(base(context) + f"/workflow-runs/{row.run_id}", headers=auth(context)).json()
        cancelled = context.client.post(
            base(context) + f"/workflow-runs/{row.run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": current["revision"]},
        )
        assert_that(cancelled.json()["state"], equal_to("CANCELLING"))
        with pytest.raises(WorkflowConflict, match="fenced"):
            repository.admit(row.id, token)
        repository.advance(row.run_id)
        assert_that(repository.inspect(row.run_id)[1].state, equal_to("STOPPING"))
        repository.advance(row.run_id, stopped=True)
        assert_that(repository.inspect(row.run_id)[0].state, equal_to("CANCELLED"))


def test_revocation_fences_model_result_and_hides_run() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        with context.postgres_delegate.engine.begin() as connection:
            connection.execute(text("DELETE FROM user_organization WHERE user_id=:user"), {"user": context.user.id})
        with pytest.raises(WorkflowConflict, match="fenced"):
            repository.admit(row.id, token)
        repository.advance(row.run_id)
        assert_that(repository.inspect(row.run_id)[0].state, equal_to("PAUSED"))


def test_forged_attempt_capabilities_are_rejected() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        repository.admit(row.id, token)
        with pytest.raises(WorkflowConflict, match="Invalid"):
            repository.admit(row.id, "forged")


def test_agent_restart_during_attempt_shutdown_does_not_resume_a_paused_run() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        context.agent.status = AgentStatus.STOPPED
        context.injector.get(AgentRepository).save(context.agent)
        repository.advance(row.run_id)
        assert_that(repository.inspect(row.run_id)[0].state, equal_to("PAUSED"))
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        repository.advance(row.run_id, stopped=True)
        repository.advance(row.run_id)
        run, stopped = repository.inspect(row.run_id)
        assert_that((run.state, run.generation, stopped.state), equal_to(("PAUSED", row.generation, "STOPPED")))
        with pytest.raises(WorkflowConflict, match="fenced"):
            repository.admit(row.id, token)


def test_duplicate_wakeups_do_not_reemit_pause_after_a_completed_step() -> None:
    from api.tests.helpers.workflows import draft

    with given(_RUN_GIVEN) as context:
        body = draft()
        body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Next step"})
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
        response, _, _ = start(context, saved)
        repository, row, token = attempt(context, response.json()["id"])
        context.injector.get(WorkflowRunService).result(row.id, token, result())
        context.agent.status = AgentStatus.STOPPED
        context.injector.get(AgentRepository).save(context.agent)
        repository.advance(row.run_id)
        before = repository.inspect(row.run_id)[0]
        with Session(context.postgres_delegate.engine) as session:
            events_before = len(session.exec(select(OutboxMessage)).all())
        repository.advance(row.run_id)
        repository.advance(row.run_id)
        after = repository.inspect(row.run_id)[0]
        assert_that((after.state, after.revision), equal_to(("PAUSED", before.revision)))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(len(session.exec(select(OutboxMessage)).all()), equal_to(events_before))


def test_lost_attempt_restarts_fresh_without_replaying_checkpoint() -> None:
    from api.tests.helpers.workflows import draft

    with given(_RUN_GIVEN) as context:
        body = draft()
        body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Next step"})
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
        response, _, _ = start(context, saved)
        repository, first, token = attempt(context, response.json()["id"])
        first_result = result()
        first_result.summary = "Source prepared: alpha=17, beta=29"
        context.injector.get(WorkflowRunService).result(first.id, token, first_result)
        second, _ = repository.advance(first.run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(second.id, repository.token(second.id))
        assert_that("Source prepared: alpha=17, beta=29" in handoff["prompt"], is_(True))
        assert_that(handoff["session_id"], equal_to(f"workflow-{second.id}"))
        repository.advance(first.run_id, lost=True)
        repository.advance(first.run_id, stopped=True)
        fresh, _ = repository.advance(first.run_id)
        assert_that((fresh.step_index, fresh.generation), equal_to((1, 3)))
        assert_that(fresh.id != second.id, is_(True))
        with pytest.raises(WorkflowConflict, match="fenced"):
            repository.admit(second.id, repository.token(second.id))
        _, _, packet = repository.admit(fresh.id, repository.token(fresh.id))
        assert_that(packet["completed_steps"], has_length(1))


def test_tenant_hidden_reader_cannot_read_run_or_history() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = response.json()["id"]
        switch_member(context)
        for suffix in ("", "/history"):
            assert_that(
                context.client.get(
                    base(context) + f"/workflow-runs/{run_id}{suffix}", headers=auth(context)
                ).status_code,
                equal_to(404),
            )
        assert_that(rerun(context, run_id).status_code, equal_to(404))


def settle(context, run_id: str) -> None:
    repository, row, token = attempt(context, run_id)
    repository.complete(row.id, token, result())


def rerun(context, run_id: str, **body):
    body = {"client_request_id": str(uuid4()), **body}
    return context.client.post(base(context) + f"/workflow-runs/{run_id}/re-run", headers=auth(context), json=body)


def run_detail(context, run_id: str) -> dict:
    return context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()


def test_rerun_starts_a_new_run_of_the_same_version_and_inputs_and_says_so() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        original_id = response.json()["id"]
        settle(context, original_id)
        before = context.client.get(base(context) + f"/workflow-runs/{original_id}/history", headers=auth(context))
        again = rerun(context, original_id)
        assert_that(again.status_code, equal_to(202), again.text)
        new = again.json()
        assert_that(new["id"] != original_id, is_(True))
        assert_that(
            (new["version_id"], new["inputs"], new["rerun_of_run_id"], new["state"]),
            equal_to((saved["version"]["id"], {"period": "This week"}, original_id, "QUEUED")),
        )
        assert_that(new["initiating_user_id"], equal_to(str(context.user.id)))
        history = context.client.get(
            base(context) + f"/workflow-runs/{new['id']}/history", headers=auth(context)
        ).json()
        assert_that(
            [(item["kind"], item["detail"]) for item in history["items"]],
            equal_to([("RERUN_STARTED", f"Re-run of run {original_id[:8]} using version 1")]),
        )
        original = run_detail(context, original_id)
        assert_that((original["state"], original["rerun_of_run_id"]), equal_to(("SUCCEEDED", None)))
        after = context.client.get(base(context) + f"/workflow-runs/{original_id}/history", headers=auth(context))
        assert_that(after.json(), equal_to(before.json()))
        with Session(context.postgres_delegate.engine) as session:
            events = session.exec(select(OutboxMessage).where(OutboxMessage.event_name == "workflow.run.changed")).all()
            assert_that(len([e for e in events if e.correlation_id == UUID(new["id"])]), equal_to(1))


def test_rerun_keeps_the_original_version_after_a_newer_one_is_saved() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        settle(context, response.json()["id"])
        newer = context.client.post(
            base(context) + f"/workflows/{saved['id']}/versions",
            headers=auth(context),
            json={"draft": {**saved["version"]["draft"], "description": "Changed"}, "expected_revision": 1},
        )
        assert_that(newer.status_code, equal_to(201), newer.text)
        again = rerun(context, response.json()["id"]).json()
        assert_that(again["version_id"], equal_to(saved["version"]["id"]))
        assert_that(again["version_number"], equal_to(1))


def test_rerun_accepts_nothing_but_its_request_identity() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        settle(context, response.json()["id"])
        for extra in ({"inputs": {"period": "Other"}}, {"version_id": str(uuid4())}):
            assert_that(rerun(context, response.json()["id"], **extra).status_code, equal_to(422))
        assert_that(
            context.client.get(base(context) + "/workflow-runs", headers=auth(context)).json()["total"], equal_to(1)
        )


def test_only_a_settled_run_can_be_run_again() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = response.json()["id"]
        assert_that(run_detail(context, run_id)["allowed_actions"], equal_to(["cancel"]))
        assert_that(rerun(context, run_id).status_code, equal_to(409))
        settle(context, run_id)
        assert_that(run_detail(context, run_id)["allowed_actions"], equal_to(["rerun"]))
        assert_that(rerun(context, run_id).status_code, equal_to(202))


def test_rerun_retries_are_stable_and_identity_reuse_for_another_run_conflicts() -> None:
    with given(_RUN_GIVEN) as context:
        first, saved, _ = start(context)
        second, _, _ = start(context, saved)
        settle(context, first.json()["id"])
        settle(context, second.json()["id"])
        identity = str(uuid4())
        one = rerun(context, first.json()["id"], client_request_id=identity)
        retry = rerun(context, first.json()["id"], client_request_id=identity)
        assert_that(retry.json()["id"], equal_to(one.json()["id"]))
        assert_that(rerun(context, second.json()["id"], client_request_id=identity).status_code, equal_to(409))


def test_rerun_refuses_a_run_whose_inputs_were_removed_by_retention() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = response.json()["id"]
        settle(context, run_id)
        with Session(context.postgres_delegate.engine) as session:
            run = session.get_one(WorkflowRun, UUID(run_id))
            run.settled_at = datetime.now(UTC) - timedelta(days=91)
            session.add(run)
            session.commit()
        context.injector.get(WorkflowRunRepository).expire_content()
        assert_that(run_detail(context, run_id)["allowed_actions"], equal_to([]))
        assert_that(rerun(context, run_id).status_code, equal_to(409))


def test_rerun_retry_still_returns_the_run_after_retention_removed_the_source_inputs() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = response.json()["id"]
        settle(context, run_id)
        identity = str(uuid4())
        first = rerun(context, run_id, client_request_id=identity)
        assert_that(first.status_code, equal_to(202), first.text)
        with Session(context.postgres_delegate.engine) as session:
            source = session.get_one(WorkflowRun, UUID(run_id))
            source.settled_at = datetime.now(UTC) - timedelta(days=91)
            session.add(source)
            session.commit()
        context.injector.get(WorkflowRunRepository).expire_content()
        retry = rerun(context, run_id, client_request_id=identity)
        assert_that(retry.json()["id"], equal_to(first.json()["id"]))
        assert_that(rerun(context, run_id).status_code, equal_to(409))


def test_rerun_requires_a_running_agent() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        settle(context, response.json()["id"])
        context.agent.status = AgentStatus.STOPPED
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(rerun(context, response.json()["id"]).status_code, equal_to(409))


def test_run_again_is_only_advertised_when_a_re_run_could_start() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        run_id = response.json()["id"]
        settle(context, run_id)

        def advertised() -> tuple[list[str], list[str]]:
            listed = context.client.get(base(context) + "/workflow-runs", headers=auth(context)).json()["items"]
            return run_detail(context, run_id)["allowed_actions"], listed[0]["allowed_actions"]

        assert_that(advertised(), equal_to((["rerun"], ["rerun"])))
        context.agent.status = AgentStatus.STOPPED
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(advertised(), equal_to(([], [])))
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        archived = context.client.post(
            base(context) + f"/workflows/{saved['id']}/archive",
            headers=auth(context),
            json={"expected_revision": saved["revision"]},
        )
        assert_that(archived.status_code, equal_to(204), archived.text)
        assert_that(advertised(), equal_to(([], [])))
        assert_that(rerun(context, run_id).status_code, equal_to(409))


def test_rerun_refuses_a_source_whose_inputs_were_removed_after_it_was_read() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        run_id = UUID(response.json()["id"])
        settle(context, str(run_id))
        with Session(context.postgres_delegate.engine) as session:
            run = session.get_one(WorkflowRun, run_id)
            run.inputs, run.content_expired = {}, True
            session.add(run)
            session.commit()
        repository = context.injector.get(WorkflowRunRepository)
        with pytest.raises(WorkflowConflict):
            repository.start(
                UUID(saved["id"]),
                context.agent.id,
                AuthorizationScope(organization_id=context.organization.id),
                WorkflowRunCreate(version_id=UUID(saved["version"]["id"]), client_request_id=uuid4(), inputs={}),
                context.user.id,
                context.organization_user.id,
                "openclaw",
                run_id,
            )


@pytest.mark.parametrize("general", [False, True])
def test_viewer_reads_runs_but_cannot_start_or_cancel(general) -> None:
    from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
    from api.tests.steps.agent import there_is_agent_access

    with given(_RUN_GIVEN) as context:
        response, saved, payload = start(context)
        run_id = response.json()["id"]
        switch_member(context)
        if general:
            context.agent.general_access_role_id = AGENT_VIEWER_ROLE_ID
            context.injector.get(AgentRepository).save(context.agent)
        else:
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        detail = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context))
        assert_that(detail.status_code, equal_to(200))
        assert_that(detail.json()["allowed_actions"], equal_to([]))
        assert_that(
            context.client.get(base(context) + "/workflow-runs", headers=auth(context)).json()["total"], equal_to(1)
        )
        assert_that(
            context.client.post(
                base(context) + f"/workflows/{saved['id']}/runs", headers=auth(context), json=payload
            ).status_code,
            equal_to(403),
        )
        assert_that(
            context.client.post(
                base(context) + f"/workflow-runs/{run_id}/cancel", headers=auth(context), json={"expected_revision": 1}
            ).status_code,
            equal_to(403),
        )
        assert_that(rerun(context, run_id).status_code, equal_to(403))


def test_postgresql_rejects_repinning_a_started_run() -> None:
    from sqlalchemy.exc import DBAPIError

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        with pytest.raises(DBAPIError, match="pins are immutable"):
            with context.postgres_delegate.engine.begin() as connection:
                connection.execute(
                    text("UPDATE workflow_run SET runtime='another-runtime' WHERE id=:run_id"),
                    {"run_id": response.json()["id"]},
                )


def test_authoring_setting_does_not_disable_saved_workflow_execution() -> None:
    from api.tests.helpers.workflows import set_authoring

    with given(_RUN_GIVEN) as context:
        saved = create(context)
        set_authoring(context, False)
        response, _, _ = start(context, saved)
        assert_that(response.status_code, equal_to(202))
        repository, row, token = attempt(context, response.json()["id"])
        admitted, _, _ = repository.admit(row.id, token)
        assert_that(str(admitted.id), equal_to(response.json()["id"]))


@pytest.mark.parametrize("extra", [{"artifact": {"format": "text", "content": "file"}}, {"final_artifact": None}])
def test_file_result_fields_are_rejected(extra: dict) -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        published = context.client.post(
            f"/workflow-runtime/v1/attempts/{row.id}/result",
            headers={"Authorization": f"Bearer {token}"},
            json={**result().model_dump(), **extra},
        )
        assert_that(published.status_code, equal_to(422))
        assert_that(repository.inspect(row.run_id)[0].next_step, equal_to(0))


def test_text_result_and_duplicate_publication_are_durable_without_storage() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        assert_that(response.status_code, equal_to(202))
        assert_that(saved["execution_available"], is_(True))
        repository, row, token = attempt(context, response.json()["id"])
        url = f"/workflow-runtime/v1/attempts/{row.id}/result"
        for _ in range(2):
            published = context.client.post(
                url, headers={"Authorization": f"Bearer {token}"}, json=result().model_dump()
            )
            assert_that(published.status_code, equal_to(204), published.text)
        assert_that(repository.inspect(row.run_id)[0].state, equal_to("SUCCEEDED"))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(WorkflowCheckpoint)).all(), has_length(1))
        detail = context.client.get(base(context) + f"/workflow-runs/{row.run_id}", headers=auth(context)).json()
        assert_that(detail["final_summary"], equal_to(result().summary))
        assert_that(detail["steps"][-1]["summary"], equal_to(result().summary))
        for suffix in ["/artifacts", f"/artifacts/{uuid4()}/content", f"/artifacts/{uuid4()}/preview"]:
            assert_that(
                context.client.get(
                    base(context) + f"/workflow-runs/{row.run_id}" + suffix, headers=auth(context)
                ).status_code,
                equal_to(404),
            )


def test_text_retention_expires_settled_content_but_preserves_active_checkpoints() -> None:
    from api.tests.helpers.workflows import draft

    with given(_RUN_GIVEN) as context:
        body = draft()
        body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Next step"})
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
        active, _, _ = start(context, saved)
        repository, current, token = attempt(context, active.json()["id"])
        repository.complete(current.id, token, result())
        settled, _, _ = start(context)
        _, completed, token = attempt(context, settled.json()["id"])
        repository.complete(completed.id, token, result())
        with Session(context.postgres_delegate.engine) as session:
            run = session.get_one(WorkflowRun, completed.run_id)
            run.settled_at = datetime.now(UTC) - timedelta(days=91)
            session.add(run)
            session.commit()
        repository.expire_content()
        active_detail = context.client.get(
            base(context) + f"/workflow-runs/{current.run_id}", headers=auth(context)
        ).json()
        assert_that(active_detail["steps"][0]["summary"], equal_to(result().summary))
        expired = context.client.get(base(context) + f"/workflow-runs/{completed.run_id}", headers=auth(context)).json()
        assert_that(expired["inputs"], equal_to({}))
        assert_that(expired["final_summary"], is_(None))
        assert_that(expired["state"], equal_to("SUCCEEDED"))


def test_organization_deletion_cascades_workflow_execution_records() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        repository.complete(row.id, token, result())
        context.agent.deleted_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.agent)
        deleted = context.client.delete(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))
        assert_that(deleted.status_code, equal_to(204), deleted.text)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(WorkflowRun)).all(), equal_to([]))
            assert_that(session.exec(select(WorkflowCheckpoint)).all(), equal_to([]))


def _agent_reachable(context):
    from api.core.config import Config
    from api.infrastructure.crypto import encrypt_token
    from api.infrastructure.kubernetes.client import KubernetesClient

    context.agent.communication_key_encrypted = encrypt_token(
        "trigger-key", context.injector.get(Config).agent_token_encryption_key
    )
    context.injector.get(AgentRepository).save(context.agent)
    k8s = context.injector.get(KubernetesClient)
    k8s.proxy_to_agent.reset_mock(side_effect=True)
    k8s.proxy_to_agent.return_value = (202, b"{}", {})
    return k8s


def test_controller_sends_each_step_to_the_agent_once() -> None:
    import json

    from api.domains.workflows.controller import WorkflowController

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        k8s = _agent_reachable(context)
        controller = context.injector.get(WorkflowController)
        run_id = UUID(response.json()["id"])
        controller.wake(run_id)
        controller.wake(run_id)
        assert_that(k8s.proxy_to_agent.call_count, equal_to(1))
        service, _, port, path, method, body, headers = k8s.proxy_to_agent.call_args.args
        _, attempt_row = context.injector.get(WorkflowRunRepository).inspect(run_id)
        sent = json.loads(body)
        assert_that(
            (service, port, path, method, headers["Authorization"]),
            equal_to(
                (f"agent-{context.agent.id}", 8082, "/agent-triggers/v1/workflow-steps", "POST", "Bearer trigger-key")
            ),
        )
        assert_that(sent["attempt_id"], equal_to(str(attempt_row.id)))
        assert_that(sent["callback_url"].endswith(f"/workflow-runtime/v1/attempts/{attempt_row.id}"), is_(True))
        assert_that(attempt_row.dispatched_at is not None, is_(True))


def test_unreachable_agent_is_retried_on_the_next_pass() -> None:
    from api.domains.workflows.controller import WorkflowController

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        k8s = _agent_reachable(context)
        k8s.proxy_to_agent.side_effect = [RuntimeError("no pod"), (202, b"{}", {})]
        controller = context.injector.get(WorkflowController)
        run_id = UUID(response.json()["id"])
        controller.wake(run_id)
        assert_that(context.injector.get(WorkflowRunRepository).inspect(run_id)[1].dispatched_at, is_(None))
        controller.wake(run_id)
        assert_that(k8s.proxy_to_agent.call_count, equal_to(2))
        assert_that(context.injector.get(WorkflowRunRepository).inspect(run_id)[1].dispatched_at is not None, is_(True))


def test_cancel_stops_the_agent_session_and_settles() -> None:
    from api.domains.workflows.controller import WorkflowController

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        k8s = _agent_reachable(context)
        controller = context.injector.get(WorkflowController)
        run_id = UUID(response.json()["id"])
        controller.wake(run_id)
        _, attempt_row = context.injector.get(WorkflowRunRepository).inspect(run_id)
        current = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()
        context.client.post(
            base(context) + f"/workflow-runs/{run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": current["revision"]},
        )
        controller.wake(run_id)
        assert_that(
            k8s.proxy_to_agent.call_args.args[3], equal_to(f"/agent-triggers/v1/workflow-steps/{attempt_row.id}/stop")
        )
        assert_that(context.injector.get(WorkflowRunRepository).inspect(run_id)[0].state, equal_to("CANCELLED"))


def test_agent_reported_failure_retries_then_fails_the_run() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository = context.injector.get(WorkflowRunRepository)
        run_id = UUID(response.json()["id"])
        for expected in ("QUEUED", "QUEUED", "FAILED"):
            row, _ = repository.advance(run_id)
            failed = context.client.post(
                f"/workflow-runtime/v1/attempts/{row.id}/failure",
                headers={"Authorization": f"Bearer {repository.token(row.id)}"},
                json={"reason": "The Agent session ended without a result"},
            )
            assert_that(failed.status_code, equal_to(204), failed.text)
            assert_that(repository.inspect(run_id)[0].state, equal_to(expected))
        kinds = [
            event["kind"]
            for event in context.client.get(
                base(context) + f"/workflow-runs/{run_id}/history?page_size=50", headers=auth(context)
            ).json()["items"]
        ]
        assert_that(kinds.count("ATTEMPT_FAILED"), equal_to(3))
        assert_that(
            repository.inspect(run_id)[0].reason,
            equal_to("Attempt recovery limit reached: The Agent session ended without a result"),
        )


def test_retry_shows_the_reported_reason_and_unmet_criteria_fail_immediately() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository = context.injector.get(WorkflowRunRepository)
        run_id = UUID(response.json()["id"])

        def report(**body):
            row, _ = repository.advance(run_id)
            failed = context.client.post(
                f"/workflow-runtime/v1/attempts/{row.id}/failure",
                headers={"Authorization": f"Bearer {repository.token(row.id)}"},
                json=body,
            )
            assert_that(failed.status_code, equal_to(204), failed.text)
            return repository.inspect(run_id)[0]

        run = report(reason="Pipedrive is not connected")
        assert_that((run.state, run.reason), equal_to(("QUEUED", "Step failed, retrying: Pipedrive is not connected")))
        repository.advance(run_id)
        assert_that(repository.inspect(run_id)[0].reason, equal_to(run.reason))
        run = report(reason="Pipedrive is not connected", retryable=False)
        assert_that((run.state, run.reason), equal_to(("FAILED", "Pipedrive is not connected")))
        assert_that(run.settled_at is not None, equal_to(True))


def test_approval_request_blocks_the_run_until_a_person_acts() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, token = attempt(context, response.json()["id"])
        blocked = context.client.post(
            f"/workflow-runtime/v1/attempts/{row.id}/failure",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "The Agent needs approval to run rm -rf build.", "needs_attention": True},
        )
        assert_that(blocked.status_code, equal_to(204))
        run = context.client.get(base(context) + f"/workflow-runs/{row.run_id}", headers=auth(context)).json()
        assert_that(
            (run["state"], run["reason"]), equal_to(("BLOCKED", "The Agent needs approval to run rm -rf build."))
        )
        assert_that(repository.advance(row.run_id)[0], is_(None))
        assert_that(run["allowed_actions"], equal_to(["cancel"]))


def test_worker_events_dispatch_each_step_without_a_maintenance_pass(monkeypatch) -> None:
    from api.domains.events.handlers import EventHandlerRegistry
    from api.domains.events.processor import EventDeliveryProcessor
    from api.domains.events.repository import OutboxMessageRepository
    from api.domains.events.transport import EventDeliveryTransport
    from api.tests.helpers.workflows import draft

    pending = []

    def enqueue(_transport, delivery_id, *, metadata=None):
        pending.append(delivery_id)

    monkeypatch.setattr(EventDeliveryTransport, "enqueue", enqueue)
    with given(_RUN_GIVEN) as context:
        body = draft()
        body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Review report"})
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
        _agent_reachable(context)
        response, _, _ = start(context, saved)
        run_id = UUID(response.json()["id"])
        repository = context.injector.get(WorkflowRunRepository)
        processor = EventDeliveryProcessor(
            context.injector.get(OutboxMessageRepository), context.injector.get(EventHandlerRegistry)
        )

        def drain():
            while pending:
                assert processor.process(pending.pop(0))

        assert pending, "Starting a run must enqueue its committed wakeup"
        drain()
        for step in range(2):
            run, row = repository.inspect(run_id)
            assert (run.state, row.step_index, row.dispatched_at is not None) == ("RUNNING", step, True)
            completed = context.client.post(
                f"/workflow-runtime/v1/attempts/{row.id}/result",
                headers={"Authorization": f"Bearer {repository.token(row.id)}"},
                json=result().model_dump(),
            )
            assert completed.status_code == 204, completed.text
            assert pending, "A completed step must enqueue progression"
            drain()
        assert repository.inspect(run_id)[0].state == "SUCCEEDED"


def test_broker_outage_preserves_a_committed_run_and_pending_wakeup(monkeypatch) -> None:
    from api.domains.events.models import EventDeliveryStatus
    from api.domains.events.transport import EventDeliveryTransport

    def unavailable(_transport, delivery_id, *, metadata=None):
        raise ConnectionError("test broker unavailable")

    monkeypatch.setattr(EventDeliveryTransport, "enqueue", unavailable)
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        assert response.status_code == 202, response.text
        with Session(context.postgres_delegate.engine) as session:
            run = session.get_one(WorkflowRun, UUID(response.json()["id"]))
            delivery = session.exec(select(EventDelivery)).one()
            assert (run.state, delivery.status) == ("QUEUED", EventDeliveryStatus.PENDING)


@pytest.mark.parametrize("action", ["cancel", "failure"])
def test_worker_wakeup_handles_cancellation_and_failed_session_retry(monkeypatch, action) -> None:
    from api.domains.events.handlers import EventHandlerRegistry
    from api.domains.events.processor import EventDeliveryProcessor
    from api.domains.events.repository import OutboxMessageRepository
    from api.domains.events.transport import EventDeliveryTransport

    pending = []

    def enqueue(_transport, delivery_id, *, metadata=None):
        pending.append(delivery_id)

    monkeypatch.setattr(EventDeliveryTransport, "enqueue", enqueue)
    with given(_RUN_GIVEN) as context:
        _agent_reachable(context)
        response, _, _ = start(context)
        run_id = UUID(response.json()["id"])
        repository = context.injector.get(WorkflowRunRepository)
        processor = EventDeliveryProcessor(
            context.injector.get(OutboxMessageRepository), context.injector.get(EventHandlerRegistry)
        )

        def drain():
            while pending:
                assert processor.process(pending.pop(0))

        drain()
        run, row = repository.inspect(run_id)
        assert row is not None and row.dispatched_at is not None
        if action == "cancel":
            response = context.client.post(
                base(context) + f"/workflow-runs/{run_id}/cancel",
                headers=auth(context),
                json={"expected_revision": run.revision},
            )
            assert response.status_code == 200, response.text
        else:
            response = context.client.post(
                f"/workflow-runtime/v1/attempts/{row.id}/failure",
                headers={"Authorization": f"Bearer {repository.token(row.id)}"},
                json={"reason": "Session ended without a result"},
            )
            assert response.status_code == 204, response.text
        assert pending, "Cancellation and failed sessions must enqueue their transitions"
        drain()
        run, current = repository.inspect(run_id)
        if action == "cancel":
            assert run.state == "CANCELLED"
        else:
            assert run.state == "RUNNING"
            assert current.id != row.id and current.dispatched_at is not None


def test_step_timing_uses_first_attempt_and_completed_checkpoint_across_retries() -> None:
    from api.domains.workflows.run_models import WorkflowAttempt

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = UUID(response.json()["id"])
        initial = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()
        assert initial["steps"][0]["started_at"] is None
        assert initial["steps"][0]["completed_at"] is None
        repository, first, _ = attempt(context, str(run_id))
        beginning = datetime.now(UTC) - timedelta(minutes=5)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(WorkflowAttempt, first.id)
            row.created_at = beginning
            session.add(row)
            session.commit()
        repository.advance(run_id, stopped=True, lost=True)
        second, _ = repository.advance(run_id)
        assert second is not None
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(WorkflowAttempt, second.id)
            row.created_at = beginning + timedelta(seconds=60)
            session.add(row)
            session.commit()
        repository.complete(second.id, repository.token(second.id), result())
        end = beginning + timedelta(seconds=114)
        with Session(context.postgres_delegate.engine) as session:
            checkpoint = session.exec(select(WorkflowCheckpoint).where(WorkflowCheckpoint.run_id == run_id)).one()
            checkpoint.created_at = end
            session.add(checkpoint)
            session.commit()
        current = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()
        step = current["steps"][0]
        assert datetime.fromisoformat(step["started_at"]) == beginning
        assert datetime.fromisoformat(step["completed_at"]) == end
        assert step["summary"] == result().summary


def test_running_step_reports_its_attempt_and_an_unresponsive_agent() -> None:
    from api.domains.workflows.run_models import WorkflowAttempt

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = response.json()["id"]
        url = base(context) + f"/workflow-runs/{run_id}"
        assert context.client.get(url, headers=auth(context)).json()["attempt"] is None
        repository, row, _ = attempt(context, run_id)
        live = context.client.get(url, headers=auth(context)).json()["attempt"]
        assert (live["number"], live["limit"], live["agent_unresponsive"]) == (1, 3, False)
        with Session(context.postgres_delegate.engine) as session:
            stored = session.get_one(WorkflowAttempt, row.id)
            stored.created_at = datetime.now(UTC) - timedelta(minutes=2)
            session.add(stored)
            session.commit()
        assert context.client.get(url, headers=auth(context)).json()["attempt"]["agent_unresponsive"] is True
        repository.mark_dispatched(row.id)
        assert context.client.get(url, headers=auth(context)).json()["attempt"]["agent_unresponsive"] is False


def test_timeouts_keep_the_reported_failure_and_name_an_agent_that_never_accepted() -> None:
    from api.domains.workflows.run_models import WorkflowAttempt

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository = context.injector.get(WorkflowRunRepository)
        run_id = UUID(response.json()["id"])

        def expire(row) -> str | None:
            with Session(context.postgres_delegate.engine) as session:
                stored = session.get_one(WorkflowAttempt, row.id)
                stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                session.add(stored)
                session.commit()
            repository.advance(run_id)
            repository.advance(run_id, stopped=True)
            return repository.inspect(run_id)[0].reason

        row, _ = repository.advance(run_id)
        context.client.post(
            f"/workflow-runtime/v1/attempts/{row.id}/failure",
            headers={"Authorization": f"Bearer {repository.token(row.id)}"},
            json={"reason": "Pipedrive is not configured"},
        )
        row, _ = repository.advance(run_id)
        repository.mark_dispatched(row.id)
        assert_that(
            expire(row),
            equal_to("Step failed, retrying: Pipedrive is not configured (last attempt: The attempt timed out)"),
        )
        row, _ = repository.advance(run_id)
        assert_that(
            expire(row),
            equal_to(
                "Attempt recovery limit reached: Pipedrive is not configured "
                "(last attempt: The Agent did not accept the step)"
            ),
        )
