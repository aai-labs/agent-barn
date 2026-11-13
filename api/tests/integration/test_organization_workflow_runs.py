"""Organization workflows run on an Agent chosen per run; the run is reached through that Agent (AF-439)."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.workflows.run_models import WorkflowRun
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.workflows import draft
from api.tests.integration.test_workflow_approvals import _raise
from api.tests.integration.test_workflow_runs import (
    _RUN_GIVEN,
    attempt,
    rerun,
    result,
    run_payload,
    runs_url,
    settle,
    start,
)
from api.tests.integration.test_workflows import auth, base, create, member_headers, post_draft
from api.tests.steps.agent import there_is_agent_access, there_is_an_agent


def second_agent(context, name: str = "Second Agent"):
    """Another Agent in the Organization; the context keeps pointing at the first."""
    first = context.agent
    there_is_an_agent(name=name, status=AgentStatus.RUNNING)(context)
    other, context.agent = context.agent, first
    return other


def grant(context, agent, role_id) -> None:
    there_is_agent_access(membership_id=context.member_membership.id, agent_id=agent.id, access_role_id=role_id)(
        context
    )


def delete_agent(context, agent) -> None:
    agent.deleted_at = datetime.now(UTC)
    context.injector.get(AgentRepository).save(agent)


def listed(context, query: str = "", headers: dict | None = None) -> list[dict]:
    response = context.client.get(runs_url(context) + query, headers=headers or auth(context))
    assert_that(response.status_code, equal_to(200), response.text)
    assert_that(response.json()["total"], equal_to(len(response.json()["items"])))
    return response.json()["items"]


def test_one_workflow_runs_on_different_agents_and_each_run_names_its_agent() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        other = second_agent(context)

        with when("the same workflow is started on two Agents"):
            first, _, _ = start(context, saved, title="Week 12 report")
            second, _, _ = start(context, saved, agent=other)

        with then("each run carries its own Agent and title"):
            assert_that((first.status_code, second.status_code), equal_to((202, 202)))
            run = first.json()
            assert_that(
                (run["agent_id"], run["agent_name"], run["agent_archived"], run["title"], run["name"]),
                equal_to((str(context.agent.id), context.agent.name, False, "Week 12 report", "Weekly report")),
            )
            assert_that((second.json()["agent_id"], second.json()["title"]), equal_to((str(other.id), None)))

        with then("runs are listed across Agents and filtered by Agent or workflow"):
            unrelated = create(context)
            third, _, _ = start(context, unrelated)
            assert_that(len(listed(context)), equal_to(3))
            assert_that(
                [item["id"] for item in listed(context, f"?agent_id={other.id}")], equal_to([second.json()["id"]])
            )
            assert_that(
                {item["id"] for item in listed(context, f"?workflow_id={saved['id']}")},
                equal_to({first.json()["id"], second.json()["id"]}),
            )
            assert_that(
                [item["id"] for item in listed(context, f"?workflow_id={unrelated['id']}&agent_id={context.agent.id}")],
                equal_to([third.json()["id"]]),
            )


def test_run_title_is_bounded() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context, title="t" * 201)
        assert_that(response.status_code, equal_to(422))
        assert_that(listed(context), equal_to([]))


def test_reusing_a_start_identity_for_another_agent_conflicts() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, payload = start(context)
        other = second_agent(context)
        reused = context.client.post(
            runs_url(context), headers=auth(context), json={**payload, "agent_id": str(other.id)}
        )
        assert_that(reused.status_code, equal_to(409))
        assert_that("different Agent" in reused.json()["detail"], is_(True))
        assert_that([item["id"] for item in listed(context)], equal_to([response.json()["id"]]))
        # The same identity on the same Agent is still the same run.
        retry = context.client.post(runs_url(context), headers=auth(context), json=payload)
        assert_that(retry.json()["id"], equal_to(response.json()["id"]))
        assert_that(saved["id"], equal_to(retry.json()["workflow_id"]))


def test_starting_needs_update_on_the_chosen_agent_not_ownership_of_the_workflow() -> None:
    with given(_RUN_GIVEN) as context:
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        saved = create(context)
        readable, editable = second_agent(context, "Readable Agent"), second_agent(context, "Editable Agent")
        member = member_headers(context)
        grant(context, readable, AGENT_VIEWER_ROLE_ID)
        grant(context, editable, AGENT_EDITOR_ROLE_ID)

        def attempt_start(agent):
            return context.client.post(runs_url(context), headers=member, json=run_payload(context, saved, agent))

        with then("an Agent the Member cannot see is not found"):
            assert_that(attempt_start(context.agent).status_code, equal_to(404))
        with then("an Agent the Member can only read is refused"):
            assert_that(attempt_start(readable).status_code, equal_to(403))
        with then("a Member runs another Member's workflow on an Agent they can update"):
            response = attempt_start(editable)
            assert_that(response.status_code, equal_to(202), response.text)
            assert_that(response.json()["initiating_user_id"], equal_to(str(context.member.id)))
            assert_that(response.json()["allowed_actions"], equal_to(["cancel"]))
        with then("a workflow of another Organization is not found"):
            payload = run_payload(context, saved, editable, workflow_id=str(uuid4()))
            assert_that(context.client.post(runs_url(context), headers=member, json=payload).status_code, equal_to(404))


def test_member_sees_and_acts_only_on_runs_of_agents_they_can_reach() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        hidden_run, _, _ = start(context, saved)
        readable = second_agent(context, "Readable Agent")
        readable_run, _, _ = start(context, saved, agent=readable)
        member = member_headers(context)
        grant(context, readable, AGENT_VIEWER_ROLE_ID)
        hidden_url = runs_url(context) + f"/{hidden_run.json()['id']}"
        readable_url = runs_url(context) + f"/{readable_run.json()['id']}"

        with then("lists hold only runs on Agents the Member can read"):
            assert_that([item["id"] for item in listed(context, headers=member)], equal_to([readable_run.json()["id"]]))
            assert_that(listed(context, f"?agent_id={context.agent.id}", member), equal_to([]))
            assert_that(len(listed(context, f"?workflow_id={saved['id']}", member)), equal_to(1))

        with then("a run on an Agent the Member cannot read does not exist for them"):
            for method, suffix, body in [
                ("GET", "", None),
                ("GET", "/history", None),
                ("POST", "/cancel", {"expected_revision": 1}),
                ("POST", "/re-run", {"client_request_id": str(uuid4())}),
                ("POST", f"/approvals/{uuid4()}/decision", {"decision": "approve"}),
            ]:
                response = context.client.request(method, hidden_url + suffix, headers=member, json=body)
                assert_that(response.status_code, equal_to(404), suffix)

        with then("a run the Member can only read offers and accepts no actions"):
            detail = context.client.get(readable_url, headers=member)
            assert_that(detail.status_code, equal_to(200))
            assert_that(detail.json()["allowed_actions"], equal_to([]))
            assert_that(context.client.get(readable_url + "/history", headers=member).status_code, equal_to(200))
            for suffix, body in [
                ("/cancel", {"expected_revision": 1}),
                ("/re-run", {"client_request_id": str(uuid4())}),
                (f"/approvals/{uuid4()}/decision", {"decision": "approve"}),
            ]:
                response = context.client.post(readable_url + suffix, headers=member, json=body)
                assert_that(response.status_code, equal_to(403), suffix)


def test_workflow_list_counts_the_runs_and_names_the_default_agent_each_viewer_can_read() -> None:
    with given(_RUN_GIVEN) as context:
        readable = second_agent(context, "Readable Agent")
        on_readable = create(context, default_agent_id=readable.id)
        on_hidden = create(context, default_agent_id=context.agent.id)
        unrun = create(context)
        for workflow, agent in [
            (on_readable, context.agent),
            (on_readable, readable),
            (on_readable, readable),
            (on_hidden, None),
        ]:
            response, _, _ = start(context, workflow, agent=agent)
            assert_that(response.status_code, equal_to(202), response.text)
        member = member_headers(context)
        grant(context, readable, AGENT_VIEWER_ROLE_ID)

        def cards(headers: dict) -> dict[str, dict]:
            response = context.client.get(base(context) + "/workflows", headers=headers)
            assert_that(response.status_code, equal_to(200), response.text)
            return {item["id"]: item for item in response.json()["items"]}

        with then("the Owner sees every run and every default Agent"):
            owner = cards(auth(context))
            assert_that(owner[on_readable["id"]]["run_count"], equal_to(3))
            assert_that(owner[on_readable["id"]]["default_agent_name"], equal_to("Readable Agent"))
            assert_that(owner[on_hidden["id"]]["run_count"], equal_to(1))
            assert_that(owner[on_hidden["id"]]["default_agent_name"], equal_to(context.agent.name))
            assert_that(owner[unrun["id"]]["run_count"], equal_to(0))
            assert_that(owner[unrun["id"]]["default_agent_name"], equal_to(None))

        with then("a Member counts only runs on Agents they can read and sees only such a default Agent"):
            seen = cards(member)
            assert_that(seen[on_readable["id"]]["run_count"], equal_to(2))
            assert_that(seen[on_readable["id"]]["default_agent_name"], equal_to("Readable Agent"))
            assert_that(seen[on_hidden["id"]]["run_count"], equal_to(0))
            assert_that(seen[on_hidden["id"]]["default_agent_id"], equal_to(None))
            assert_that(seen[on_hidden["id"]]["default_agent_name"], equal_to(None))


def test_runs_are_filtered_by_active_or_settled() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        done, _, _ = start(context, saved)
        settle(context, done.json()["id"])
        running, _, _ = start(context, saved)
        assert_that([item["id"] for item in listed(context, "?status=active")], equal_to([running.json()["id"]]))
        assert_that([item["id"] for item in listed(context, "?status=settled")], equal_to([done.json()["id"]]))
        assert_that(len(listed(context)), equal_to(2))
        invalid = context.client.get(runs_url(context) + "?status=paused", headers=auth(context))
        assert_that(invalid.status_code, equal_to(422))


def test_the_approvals_inbox_spans_agents_the_member_can_read() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        hidden_run, _, _ = start(context, saved)
        _, hidden_attempt, hidden_token = attempt(context, hidden_run.json()["id"])
        _raise(context, hidden_attempt, hidden_token)
        readable = second_agent(context, "Readable Agent")
        readable_run, _, _ = start(context, saved, agent=readable)
        _, readable_attempt, readable_token = attempt(context, readable_run.json()["id"])
        request_id = _raise(context, readable_attempt, readable_token)
        member = member_headers(context)
        grant(context, readable, AGENT_VIEWER_ROLE_ID)

        assert_that(len(listed(context, "?awaiting_decision=true")), equal_to(2))
        [waiting] = listed(context, "?awaiting_decision=true", member)
        assert_that(
            (waiting["id"], waiting["approval"]["id"], waiting["agent_name"]),
            equal_to((readable_run.json()["id"], request_id, "Readable Agent")),
        )


def test_rerun_stays_on_the_source_runs_agent_and_keeps_its_title() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        other = second_agent(context)
        source, _, _ = start(context, saved, agent=other, title="Week 12 report")
        repository, row, token = attempt(context, source.json()["id"])
        repository.complete(row.id, token, result())
        again = rerun(context, source.json()["id"])
        assert_that(again.status_code, equal_to(202), again.text)
        assert_that(
            (again.json()["agent_id"], again.json()["title"], again.json()["rerun_of_run_id"]),
            equal_to((str(other.id), "Week 12 report", source.json()["id"])),
        )


def test_runs_of_a_deleted_agent_stay_readable_but_nothing_more_can_be_done() -> None:
    with given(_RUN_GIVEN) as context:
        saved = create(context)
        settled, _, _ = start(context, saved)
        settle(context, settled.json()["id"])
        active, _, _ = start(context, saved)
        member = member_headers(context)
        grant(context, context.agent, AGENT_EDITOR_ROLE_ID)
        outsider = member_headers(context)

        with when("the Agent is deleted"):
            delete_agent(context, context.agent)

        settled_url = runs_url(context) + f"/{settled.json()['id']}"
        active_url = runs_url(context) + f"/{active.json()['id']}"

        with then("its runs stay readable under the same agent.read rule, marked archived, with no actions"):
            for headers in (auth(context), member):
                detail = context.client.get(settled_url, headers=headers)
                assert_that(detail.status_code, equal_to(200))
                assert_that(
                    (detail.json()["agent_archived"], detail.json()["agent_name"], detail.json()["allowed_actions"]),
                    equal_to((True, context.agent.name, [])),
                )
                assert_that(context.client.get(settled_url + "/history", headers=headers).status_code, equal_to(200))
                items = listed(context, headers=headers)
                assert_that(len(items), equal_to(2))
                assert_that(
                    {(item["agent_archived"], tuple(item["allowed_actions"])) for item in items}, equal_to({(True, ())})
                )
            assert_that(context.client.get(settled_url, headers=outsider).status_code, equal_to(404))
            assert_that(listed(context, headers=outsider), equal_to([]))

        with then("cancel, decide and re-run are refused"):
            revision = context.client.get(active_url, headers=auth(context)).json()["revision"]
            for url, body in [
                (active_url + "/cancel", {"expected_revision": revision}),
                (active_url + f"/approvals/{uuid4()}/decision", {"decision": "approve"}),
                (settled_url + "/re-run", {"client_request_id": str(uuid4())}),
            ]:
                for headers in (auth(context), member):
                    response = context.client.post(url, headers=headers, json=body)
                    assert_that(response.status_code, equal_to(409), url)

        with then("a new run cannot be started on it"):
            payload = run_payload(context, saved)
            assert_that(
                context.client.post(runs_url(context), headers=auth(context), json=payload).status_code, equal_to(404)
            )

        with then("the run that was still active ends as cancelled once the controller advances it"):
            repository = context.injector.get(WorkflowRunRepository)
            repository.advance(UUID(active.json()["id"]))
            run = context.client.get(active_url, headers=auth(context)).json()
            assert_that((run["state"], run["allowed_actions"]), equal_to(("CANCELLED", [])))


def test_a_running_step_on_a_deleted_agent_is_stopped_then_cancelled() -> None:
    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        repository, row, _ = attempt(context, response.json()["id"])
        delete_agent(context, context.agent)
        repository.advance(row.run_id)
        assert_that(repository.inspect(row.run_id)[1].state, equal_to("STOPPING"))
        repository.advance(row.run_id, stopped=True)
        assert_that(repository.inspect(row.run_id)[0].state, equal_to("CANCELLED"))


def test_postgresql_keeps_a_run_on_its_agent_and_inside_the_workflows_organization() -> None:
    from api.tests.steps.organization import there_is_an_organization

    with given(_RUN_GIVEN) as context:
        response, _, _ = start(context)
        run_id = UUID(response.json()["id"])
        other = second_agent(context)

        with then("a started run cannot be moved to another Agent"):
            with pytest.raises(DBAPIError, match="pins are immutable"):
                with context.postgres_delegate.engine.begin() as connection:
                    connection.execute(
                        text("UPDATE workflow_run SET agent_id = :agent WHERE id = :run"),
                        {"agent": other.id, "run": run_id},
                    )

        with then("a run cannot be created on an Agent of another Organization"):
            organization = context.organization
            there_is_an_organization(name="Other Organization")(context)
            there_is_an_agent(name="Foreign Agent", status=AgentStatus.RUNNING)(context)
            foreign, context.organization = context.agent, organization
            with pytest.raises(DBAPIError, match="workflow run agent scope mismatch"):
                with Session(context.postgres_delegate.engine) as session:
                    source = session.get_one(WorkflowRun, run_id)
                    session.add(
                        WorkflowRun(
                            workflow_id=source.workflow_id,
                            agent_id=foreign.id,
                            version_id=source.version_id,
                            initiating_user_id=source.initiating_user_id,
                            initiating_membership_id=source.initiating_membership_id,
                            client_request_id=uuid4(),
                            request_hash="forged",
                            inputs={},
                            runtime=source.runtime,
                        )
                    )
                    session.commit()


def _insert_previous_schema_workflow(connection, agent_id, author_id=None) -> UUID:
    workflow_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO workflow (id, created_at, updated_at, agent_id, revision) "
            "VALUES (:id, now(), now(), :agent, 1)"
        ),
        {"id": workflow_id, "agent": agent_id},
    )
    connection.execute(
        text(
            "INSERT INTO workflow_version "
            "(id, created_at, updated_at, workflow_id, number, snapshot, created_by_user_id) "
            "VALUES (:id, now(), now(), :workflow, 1, CAST(:snapshot AS jsonb), :author)"
        ),
        {
            "id": uuid4(),
            "workflow": workflow_id,
            "snapshot": json.dumps(draft("Earlier report")),
            "author": author_id,
        },
    )
    return workflow_id


@pytest.mark.parametrize(("has_owner", "has_admin"), [(True, True), (False, True), (False, False)])
def test_upgrade_moves_agent_workflows_to_their_organization_and_rolls_back(has_owner: bool, has_admin: bool) -> None:
    from alembic import command

    from api.tests.conftest import config

    with given(_RUN_GIVEN) as context:
        saved = create(context, default_agent_id=context.agent.id)
        response, _, _ = start(context, saved)
        run_id = response.json()["id"]
        deleted = second_agent(context, "Deleted Agent")
        author_headers = member_headers(context)
        author, author_membership = context.member, context.member_membership.id
        member_headers(context)
        departed, departed_membership = context.member, context.member_membership.id
        engine = context.postgres_delegate.engine
        owner_membership = context.organization_user.id
        later_admin, earliest_admin = uuid4(), uuid4()

        with when("the schema is rolled back to Agent-owned workflows"):
            command.downgrade(config, "d1a390e7b2c4")
        try:
            with engine.begin() as connection:
                with then("the workflow is the Agent's again"):
                    restored = connection.execute(
                        text("SELECT agent_id FROM workflow WHERE id = :id"), {"id": saved["id"]}
                    ).scalar_one()
                    assert_that(restored, equal_to(context.agent.id))
                    runs = connection.execute(text("SELECT count(*) FROM workflow_run")).scalar_one()
                    assert_that(runs, equal_to(1))
                orphan = _insert_previous_schema_workflow(connection, deleted.id)
                authored = _insert_previous_schema_workflow(connection, context.agent.id, author.id)
                left = _insert_previous_schema_workflow(connection, context.agent.id, departed.id)
                connection.execute(text("DELETE FROM user_organization WHERE id = :id"), {"id": departed_membership})
                connection.execute(text("UPDATE agent SET deleted_at = now() WHERE id = :id"), {"id": deleted.id})
                if not has_owner:
                    connection.execute(
                        text("UPDATE user_organization SET role = 'MEMBER' WHERE id = :id"), {"id": owner_membership}
                    )
                with then("the workflow.manage Permission is gone with the schema that introduced it"):
                    permission = text("SELECT count(*) FROM permissions WHERE key = 'workflow.manage'")
                    assert_that(connection.execute(permission).scalar_one(), equal_to(0))
                admins = [
                    (later_admin, datetime.now(UTC)),
                    (earliest_admin, datetime.now(UTC) - timedelta(days=1)),
                ]
                for membership_id, created_at in admins if has_admin else []:
                    connection.execute(
                        text(
                            "INSERT INTO user_organization (id, created_at, updated_at, organization_id, role) "
                            "VALUES (:id, :created_at, now(), :organization, 'ADMIN')"
                        ),
                        {"id": membership_id, "created_at": created_at, "organization": context.organization.id},
                    )
        finally:
            with when("the schema is upgraded again"):
                command.upgrade(config, "head")

        with engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    text("SELECT id, organization_id, created_by_membership_id, default_agent_id FROM workflow")
                )
            }
            run_agent = connection.execute(
                text("SELECT agent_id FROM workflow_run WHERE id = :id"), {"id": run_id}
            ).scalar_one()
            permissions = connection.execute(permission).scalar_one()
        fallback = owner_membership if has_owner else earliest_admin if has_admin else None

        with then("the workflow.manage Permission is in the catalogue again"):
            assert_that(permissions, equal_to(1))
        with then("each workflow belongs to its Agent's Organization"):
            assert_that({row.organization_id for row in rows.values()}, equal_to({context.organization.id}))
        with then("its creator is whoever saved the first version, whatever their Organization Role is now"):
            assert_that(rows[UUID(saved["id"])].created_by_membership_id, equal_to(owner_membership))
            assert_that(rows[authored].created_by_membership_id, equal_to(author_membership))
        with then("a workflow with no author, or whose author left, goes to the Owner, else the earliest Admin"):
            assert_that(rows[orphan].created_by_membership_id, equal_to(fallback))
            assert_that(rows[left].created_by_membership_id, equal_to(fallback))
        with then("a Member who wrote a workflow before the upgrade still changes it"):
            url = base(context) + f"/workflows/{authored}"
            detail = context.client.get(url, headers=author_headers).json()
            assert_that(detail["allowed_actions"], equal_to(["save_version", "archive"]))
            assert_that(detail["created_by"]["user_id"], equal_to(str(author.id)))
            response = context.client.post(
                url + "/versions", headers=author_headers, json={"expected_revision": 1, "draft": draft()}
            )
            assert_that(response.status_code, equal_to(201), response.text)
        with then("the Agent it was written for becomes its default, unless that Agent was deleted"):
            assert_that(rows[UUID(saved["id"])].default_agent_id, equal_to(context.agent.id))
            assert_that(rows[orphan].default_agent_id, is_(None))
        with then("existing runs keep the Agent that ran them"):
            assert_that(run_agent, equal_to(context.agent.id))

        if has_owner:
            with then("every workflow is served to the Organization, the deleted Agent's included"):
                items = context.client.get(base(context) + "/workflows", headers=auth(context)).json()["items"]
                assert_that(
                    {item["id"] for item in items}, equal_to({saved["id"], str(orphan), str(authored), str(left)})
                )
                detail = context.client.get(runs_url(context) + f"/{run_id}", headers=auth(context))
                assert_that(detail.json()["agent_id"], equal_to(str(context.agent.id)))


def test_another_organization_reaches_neither_the_runs_the_workflow_nor_the_agent() -> None:
    from api.tests.steps.organization import there_is_an_organization

    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        run_id, foreign_agent = response.json()["id"], context.agent
        # The same person also owns a second Organization with its own Agent and workflow.
        there_is_an_organization(name="Other Organization")(context)
        there_is_an_agent(name="Other Agent", status=AgentStatus.RUNNING)(context)
        own = create(context)

        with then("the first Organization's run is not found under the second"):
            url = runs_url(context) + f"/{run_id}"
            requests = [
                ("GET", "", None),
                ("GET", "/history", None),
                ("POST", "/cancel", {"expected_revision": 1}),
                ("POST", "/re-run", {"client_request_id": str(uuid4())}),
                ("POST", f"/approvals/{uuid4()}/decision", {"decision": "approve"}),
            ]
            for method, path, body in requests:
                answer = context.client.request(method, url + path, headers=auth(context), json=body)
                assert_that(answer.status_code, equal_to(404), f"{method} {path}: {answer.text}")
            assert_that(listed(context), equal_to([]))

        with then("its workflow cannot be started on this Organization's Agent"):
            answer = context.client.post(runs_url(context), headers=auth(context), json=run_payload(context, saved))
            assert_that(answer.status_code, equal_to(404), answer.text)

        with then("its Agent can neither run nor be the default of a workflow here"):
            answer = context.client.post(
                runs_url(context), headers=auth(context), json=run_payload(context, own, foreign_agent)
            )
            assert_that(answer.status_code, equal_to(404), answer.text)
            assert_that(post_draft(context, draft(), foreign_agent.id).status_code, equal_to(404))
            patched = context.client.patch(
                base(context) + f"/workflows/{own['id']}",
                headers=auth(context),
                json={"expected_revision": own["revision"], "default_agent_id": str(foreign_agent.id)},
            )
            assert_that(patched.status_code, equal_to(404), patched.text)
            assert_that(listed(context), equal_to([]))


def test_read_only_key_sees_runs_but_changes_none() -> None:
    with given(_RUN_GIVEN) as context:
        response, saved, _ = start(context)
        run = response.json()
        token = context.client.post(
            "/api/v1/auth/me/api-keys",
            headers=auth(context),
            json={"name": "Read-only run fixture", "access_mode": "READ_ONLY"},
        ).json()["token"]
        key = {"Authorization": f"Bearer {token}"}
        url = runs_url(context) + f"/{run['id']}"

        with then("the key reads the run and is offered no action on it"):
            seen = context.client.get(url, headers=key)
            assert_that((seen.status_code, seen.json()["allowed_actions"]), equal_to((200, [])))
            assert_that([item["id"] for item in listed(context, headers=key)], equal_to([run["id"]]))

        with then("it starts, cancels, re-runs and decides nothing"):
            requests = [
                (runs_url(context), run_payload(context, saved)),
                (url + "/cancel", {"expected_revision": run["revision"]}),
                (url + "/re-run", {"client_request_id": str(uuid4())}),
                (url + f"/approvals/{uuid4()}/decision", {"decision": "approve"}),
            ]
            for path, body in requests:
                refused = context.client.post(path, headers=key, json=body)
                assert_that(refused.status_code, equal_to(403), f"{path}: {refused.text}")
            unchanged = context.client.get(url, headers=auth(context)).json()
            assert_that((unchanged["state"], unchanged["revision"]), equal_to((run["state"], run["revision"])))
            assert_that(len(listed(context)), equal_to(1))
