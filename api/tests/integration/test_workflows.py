from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, equal_to, has_length, is_
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.workflows.models import WorkflowDraft
from api.domains.workflows.repository import WorkflowConflict, WorkflowRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.helpers.workflows import authoring_is_enabled, draft, set_authoring
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.STOPPED),
    authoring_is_enabled,
]


def base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def create(context) -> dict:
    response = context.client.post(base(context) + "/workflows", headers=auth(context), json=draft())
    assert_that(response.status_code, equal_to(201))
    return response.json()


def test_create_saves_v1_without_starting_execution_and_lists_it() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        assert_that(saved["version"]["number"], equal_to(1))
        assert_that(saved["execution_available"], is_(True))
        response = context.client.get(base(context) + "/workflows", headers=auth(context))
        assert_that(response.json()["total"], equal_to(1))
        assert_that(response.json()["items"][0]["id"], equal_to(saved["id"]))


def test_hyphenated_input_keys_are_saved_and_returned() -> None:
    with given(_GIVEN) as context:
        body = draft()
        body["inputs"][0].update(key="reporting-period", label="Reporting period")
        response = context.client.post(base(context) + "/workflows", headers=auth(context), json=body)
        assert_that(response.status_code, equal_to(201))
        saved = context.client.get(base(context) + f"/workflows/{response.json()['id']}", headers=auth(context))
        assert_that(saved.json()["version"]["draft"]["inputs"][0]["key"], equal_to("reporting-period"))


def test_list_returns_latest_version_summary_without_full_snapshots() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        body = draft("Two-step report")
        body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Review report"})
        body["inputs"] = []
        context.client.post(
            base(context) + f"/workflows/{saved['id']}/versions",
            headers=auth(context),
            json={"expected_revision": 1, "draft": body},
        )
        item = context.client.get(base(context) + "/workflows", headers=auth(context)).json()["items"][0]
        assert_that("draft" in item["version"], is_(False))
        assert_that(item["version"]["number"], equal_to(2))
        assert_that(item["version"]["name"], equal_to("Two-step report"))
        assert_that(item["version"]["description"], equal_to(body["description"]))
        assert_that((item["version"]["step_count"], item["version"]["input_count"]), equal_to((2, 0)))
        assert_that(item["allowed_actions"], equal_to(["save_version", "archive"]))


def test_label_derived_keys_are_accepted_and_duplicates_name_both_inputs() -> None:
    with given(_GIVEN) as context:
        body = draft()
        second = {**body["inputs"][0], "label": "2nd owner (e-mail)", "key": "input-2nd-owner-e-mail"}
        body["inputs"].append(second)
        assert_that(
            context.client.post(base(context) + "/workflows", headers=auth(context), json=body).status_code,
            equal_to(201),
        )
        body["inputs"][1]["key"] = body["inputs"][0]["key"]
        response = context.client.post(base(context) + "/workflows", headers=auth(context), json=body)
        assert_that(response.status_code, equal_to(422))
        [error] = response.json()["detail"]
        assert_that(error["loc"], equal_to(["body", "inputs"]))
        assert_that("Inputs 1 and 2 share the key 'period'" in error["msg"], is_(True))


def test_save_preserves_old_snapshot_and_rejects_stale_revision() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        url = base(context) + f"/workflows/{saved['id']}/versions"
        body = {"expected_revision": 1, "draft": draft("Changed report")}
        response = context.client.post(url, headers=auth(context), json=body)
        assert_that(response.status_code, equal_to(201))
        assert_that(response.json()["version"]["number"], equal_to(2))
        stale = context.client.post(url, headers=auth(context), json=body)
        assert_that(stale.status_code, equal_to(409))
        versions = context.client.get(url, headers=auth(context)).json()["items"]
        assert_that([v["draft"]["name"] for v in versions], equal_to(["Changed report", "Weekly report"]))


def test_two_concurrent_saves_claim_one_revision() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        repo = context.injector.get(WorkflowRepository)
        context.current_user_context.current_user_organization = context.organization_user
        scope = context.injector.get(AgentAuthorization).authorization_scope(
            context.current_user_context, PermissionKey.AGENT_UPDATE
        )

        def save() -> str:
            try:
                repo.save_version(
                    UUID(saved["id"]),
                    context.agent.id,
                    scope,
                    1,
                    WorkflowDraft.model_validate(draft()),
                    context.user.id,
                )
                return "saved"
            except WorkflowConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: save(), range(2)))
        assert_that(sorted(results), equal_to(["conflict", "saved"]))


def test_archive_keeps_versions_and_prevents_new_saves() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        url = base(context) + f"/workflows/{saved['id']}"
        response = context.client.post(url + "/archive", headers=auth(context), json={"expected_revision": 1})
        assert_that(response.status_code, equal_to(204))
        assert_that(context.client.get(url + "/versions", headers=auth(context)).json()["items"], has_length(1))
        response = context.client.post(
            url + "/versions", headers=auth(context), json={"expected_revision": 2, "draft": draft()}
        )
        assert_that(response.status_code, equal_to(409))


@pytest.mark.parametrize(
    "mutation",
    ["empty", "duplicate_steps", "duplicate_inputs", "blank_goal", "unknown_destination", "unknown_capability"],
)
def test_invalid_drafts_are_actionable_and_not_saved(mutation: str) -> None:
    with given(_GIVEN) as context:
        body = draft()
        if mutation == "empty":
            body["steps"] = []
        if mutation == "duplicate_steps":
            body["steps"] *= 2
        if mutation == "duplicate_inputs":
            body["inputs"] *= 2
        if mutation == "blank_goal":
            body["steps"][0]["goal"] = "   "
        if mutation == "unknown_destination":
            body["review_destination"] = "slack"
        if mutation == "unknown_capability":
            body["steps"][0]["required_capabilities"] = ["arbitrary_http"]
        response = context.client.post(base(context) + "/workflows", headers=auth(context), json=body)
        assert_that(response.status_code, equal_to(422))
        assert_that(bool(response.json()["detail"]), is_(True))
        assert_that(
            context.client.get(base(context) + "/workflows", headers=auth(context)).json()["total"], equal_to(0)
        )


def test_versions_are_immutable_in_postgres() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text("UPDATE workflow_version SET snapshot = '{}'::jsonb WHERE id = :id"),
                {"id": saved["version"]["id"]},
            )


def test_wrong_agent_and_deleted_agent_conceal_workflow() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        missing = context.client.get(
            base(context).replace(str(context.agent.id), str(uuid4())) + f"/workflows/{saved['id']}",
            headers=auth(context),
        )
        assert_that(missing.status_code, equal_to(404))
        context.agent.deleted_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(context.client.get(base(context) + "/workflows", headers=auth(context)).status_code, equal_to(404))


def switch_member(context) -> None:
    from api.domains.users.organization_users.models import OrganizationRole
    from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

    there_is_a_user(
        email=f"member-{uuid4()}@example.com", organization_id=context.organization.id, role=OrganizationRole.MEMBER
    )(context)
    there_is_an_access_token_for_user()(context)


@pytest.mark.parametrize("general", [False, True])
def test_viewer_inspects_but_cannot_author(general: bool) -> None:
    from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        saved = create(context)
        switch_member(context)
        if general:
            context.agent.general_access_role_id = AGENT_VIEWER_ROLE_ID
            context.injector.get(AgentRepository).save(context.agent)
        else:
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        response = context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context))
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["allowed_actions"], equal_to([]))
        urls = [
            ("/workflows", draft()),
            (f"/workflows/{saved['id']}/versions", {"expected_revision": 1, "draft": draft()}),
            (f"/workflows/{saved['id']}/archive", {"expected_revision": 1}),
        ]
        for path, body in urls:
            assert_that(
                context.client.post(base(context) + path, headers=auth(context), json=body).status_code, equal_to(403)
            )


@pytest.mark.parametrize("general", [False, True])
def test_editor_authors_and_access_revocation_is_immediate(general: bool) -> None:
    from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        switch_member(context)
        if general:
            context.agent.general_access_role_id = AGENT_EDITOR_ROLE_ID
            context.injector.get(AgentRepository).save(context.agent)
        else:
            there_is_agent_access(access_role_id=AGENT_EDITOR_ROLE_ID)(context)
        saved = create(context)
        if general:
            context.agent.general_access_role_id = None
            context.injector.get(AgentRepository).save(context.agent)
        else:
            with context.injector.get(PostgresRepositoryDelegate).engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM agent_access WHERE agent_id = :agent_id"), {"agent_id": context.agent.id}
                )
        response = context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context))
        assert_that(response.status_code, equal_to(404))


def test_unassigned_member_and_other_tenant_cannot_read_definitions() -> None:
    from api.tests.steps.organization import there_is_an_organization

    with given(_GIVEN) as context:
        saved = create(context)
        original_base = base(context)
        switch_member(context)
        assert_that(context.client.get(original_base + "/workflows", headers=auth(context)).status_code, equal_to(404))
        there_is_an_organization(name="Other Organization")(context)
        other_base = original_base.replace(original_base.split("/")[4], str(context.organization.id))
        assert_that(
            context.client.get(other_base + f"/workflows/{saved['id']}", headers=auth(context)).status_code,
            equal_to(404),
        )


def test_custom_permissions_and_general_access_union_author_workflows() -> None:
    from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY
    from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        switch_member(context)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        role = AgentAccessRole(organization_id=context.organization.id, name="Workflow author", is_system=False)
        delegate.save(role)
        delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[PermissionKey.AGENT_UPDATE])
        )
        there_is_agent_access(access_role_id=role.id)(context)
        context.agent.general_access_role_id = AGENT_VIEWER_ROLE_ID
        context.injector.get(AgentRepository).save(context.agent)
        saved = create(context)
        assert_that(saved["allowed_actions"], equal_to(["save_version", "archive"]))


def test_removed_membership_loses_access() -> None:
    from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        switch_member(context)
        there_is_agent_access(access_role_id=AGENT_EDITOR_ROLE_ID)(context)
        saved = create(context)
        with context.injector.get(PostgresRepositoryDelegate).engine.begin() as connection:
            connection.execute(
                text("DELETE FROM user_organization WHERE id = :id"), {"id": context.organization_user.id}
            )
        assert_that(
            context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context)).status_code,
            equal_to(403),
        )


def test_authoring_gate_keeps_reads_available_but_blocks_mutations() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        set_authoring(context, False)
        assert_that(
            context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context)).status_code,
            equal_to(200),
        )
        assert_that(
            context.client.post(base(context) + "/workflows", headers=auth(context), json=draft()).status_code,
            equal_to(409),
        )


def test_authentication_required_and_wrong_agent_version_path_is_hidden() -> None:
    with given(_GIVEN) as context:
        create(context)
        assert_that(context.client.get(base(context) + "/workflows").status_code, equal_to(401))
        assert_that(
            context.client.get(base(context) + f"/workflows/{uuid4()}/versions", headers=auth(context)).status_code,
            equal_to(404),
        )


def test_upgrade_from_previous_head_preserves_existing_agents_and_can_rollback_empty_slice() -> None:
    from alembic import command

    from api.tests.conftest import config

    with given(_GIVEN) as context:
        command.downgrade(config, "c42e91b7a603")
        try:
            # The historical schema predates current Agent model columns from staging.
            engine = context.injector.get(PostgresRepositoryDelegate).engine
            with engine.connect() as connection:
                name = connection.execute(
                    text("SELECT name FROM agent WHERE id = :id"), {"id": context.agent.id}
                ).scalar_one()
            assert_that(name, equal_to(context.agent.name))
        finally:
            command.upgrade(config, "head")
        authoring_is_enabled(context)
        created = create(context)
        assert_that(created["version"]["number"], equal_to(1))


def test_version_pagination_returns_scoped_totals_and_old_snapshots() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        url = base(context) + f"/workflows/{saved['id']}/versions"
        context.client.post(url, headers=auth(context), json={"expected_revision": 1, "draft": draft("New report")})
        response = context.client.get(url + "?page=2&page_size=1", headers=auth(context))
        assert_that(response.json()["total"], equal_to(2))
        assert_that(response.json()["items"][0]["draft"]["name"], equal_to("Weekly report"))


def test_direct_version_deletion_is_rejected_but_aggregate_purge_cascades() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text("DELETE FROM workflow_version WHERE id = :id"), {"id": saved["version"]["id"]})
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM workflow WHERE id = :id"), {"id": saved["id"]})
        assert_that(
            context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context)).status_code,
            equal_to(404),
        )


def test_unverified_member_receives_no_general_access_and_execution_remains_gated() -> None:
    from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID
    from api.domains.users.repository import UserRepository

    with given(_GIVEN) as context:
        saved = create(context)
        assert_that(
            context.client.post(
                base(context) + f"/workflows/{saved['id']}/runs",
                headers=auth(context),
                json={
                    "version_id": saved["version"]["id"],
                    "client_request_id": str(uuid4()),
                    "inputs": {"period": "This week"},
                },
            ).status_code,
            equal_to(409),
        )
        switch_member(context)
        context.user.email_verified_at = None
        context.injector.get(UserRepository).save(context.user)
        context.agent.general_access_role_id = AGENT_EDITOR_ROLE_ID
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(context.client.get(base(context) + "/workflows", headers=auth(context)).status_code, equal_to(404))


def test_personal_api_keys_preserve_read_only_and_full_authoring_contracts() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        read_key = context.client.post(
            "/api/v1/auth/me/api-keys",
            headers=auth(context),
            json={"name": "WF01 read fixture", "access_mode": "READ_ONLY"},
        ).json()["token"]
        read_auth = {"Authorization": f"Bearer {read_key}"}
        response = context.client.get(base(context) + f"/workflows/{saved['id']}", headers=read_auth)
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["allowed_actions"], equal_to([]))
        assert_that(
            context.client.post(base(context) + "/workflows", headers=read_auth, json=draft()).status_code,
            equal_to(403),
        )
        full_key = context.client.post(
            "/api/v1/auth/me/api-keys",
            headers=auth(context),
            json={"name": "WF01 author fixture", "access_mode": "FULL"},
        ).json()["token"]
        response = context.client.post(
            base(context) + f"/workflows/{saved['id']}/versions",
            headers={"Authorization": f"Bearer {full_key}"},
            json={"expected_revision": 1, "draft": draft("Key-authored report")},
        )
        assert_that(response.status_code, equal_to(201))
        assert_that(response.json()["version"]["draft"]["name"], equal_to("Key-authored report"))


def test_api_accepts_canonical_guid_step_identity_consistent_with_ui() -> None:
    with given(_GIVEN) as context:
        body = draft()
        body["steps"][0]["id"] = "11111111-1111-1111-1111-111111111111"
        response = context.client.post(base(context) + "/workflows", headers=auth(context), json=body)
        assert_that(response.status_code, equal_to(201))
        assert_that(response.json()["version"]["draft"]["steps"][0]["id"], equal_to(body["steps"][0]["id"]))


def test_manual_authoring_slice_has_no_generation_api_or_storage() -> None:
    from sqlalchemy import inspect

    with given(_GIVEN) as context:
        capabilities = context.client.get(base(context) + "/workflow-capabilities", headers=auth(context))
        assert_that(capabilities.status_code, equal_to(200))
        assert_that(capabilities.json()["authoring"], is_(True))
        assert_that("generation" in capabilities.json(), is_(False))
        assert_that(
            context.client.post(
                base(context) + "/workflow-plan-generations", headers=auth(context), json={}
            ).status_code,
            equal_to(404),
        )
        assert_that(
            context.client.get(
                base(context) + f"/workflow-plan-generations/{uuid4()}", headers=auth(context)
            ).status_code,
            equal_to(404),
        )
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        assert_that("workflow_plan_generation" in inspect(engine).get_table_names(), is_(False))


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_only_platform_admin_can_manage_workflow_setting(method: str) -> None:
    with given(_GIVEN) as context:
        url = "/api/v1/platform/settings/workflows"
        payload = {"authoring_enabled": False} if method == "PUT" else None
        assert_that(context.client.request(method, url, json=payload).status_code, equal_to(401))
        assert_that(context.client.request(method, url, headers=auth(context), json=payload).status_code, equal_to(403))


def test_platform_workflow_setting_overrides_default_and_gates_all_mutations_immediately() -> None:
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN) as context:
        saved = create(context)
        admin = platform_admin_headers(context)
        settings_url = "/api/v1/platform/settings/workflows"
        set_authoring(context, False)
        assert_that(context.client.get(settings_url, headers=admin).json()["authoring_enabled"], is_(False))
        response = context.client.put(settings_url, headers=admin, json={"authoring_enabled": True})
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["updated_at"] is not None, is_(True))
        # Saved settings apply to subsequent reads and writes.
        from api.domains.workflows.platform_repository import PlatformWorkflowRepository

        repository = context.injector.get(PlatformWorkflowRepository)
        assert_that(repository.read().authoring_enabled, is_(True))
        assert_that(
            context.client.post(base(context) + "/workflows", headers=auth(context), json=draft()).status_code,
            equal_to(201),
        )
        context.client.put(settings_url, headers=admin, json={"authoring_enabled": False})
        assert_that(repository.read().authoring_enabled, is_(False))
        capabilities = context.client.get(base(context) + "/workflow-capabilities", headers=auth(context)).json()
        assert_that(capabilities["authoring"], is_(False))
        assert_that(capabilities["execution"], is_(True))
        detail_url = base(context) + f"/workflows/{saved['id']}"
        detail = context.client.get(detail_url, headers=auth(context))
        assert_that(detail.status_code, equal_to(200))
        assert_that(detail.json()["allowed_actions"], equal_to([]))
        items = context.client.get(base(context) + "/workflows", headers=auth(context)).json()["items"]
        assert_that(all(not item["allowed_actions"] for item in items), is_(True))
        assert_that(context.client.get(detail_url + "/versions", headers=auth(context)).status_code, equal_to(200))
        for url, payload in [
            (base(context) + "/workflows", draft()),
            (detail_url + "/versions", {"expected_revision": 1, "draft": draft()}),
            (detail_url + "/archive", {"expected_revision": 1}),
        ]:
            assert_that(context.client.post(url, headers=auth(context), json=payload).status_code, equal_to(409))
        context.client.put(settings_url, headers=admin, json={"authoring_enabled": True})
        assert_that(
            context.client.post(
                detail_url + "/versions", headers=auth(context), json={"expected_revision": 1, "draft": draft()}
            ).status_code,
            equal_to(201),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"authoring_enabled": "true"},
        {"authoring_enabled": 1},
        {"authoring_enabled": None},
        {"authoring_enabled": True, "execution": True},
    ],
)
def test_invalid_platform_workflow_settings_leave_default_unchanged(payload: dict) -> None:
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN[:-1]) as context:
        headers = platform_admin_headers(context)
        url = "/api/v1/platform/settings/workflows"
        assert_that(context.client.put(url, headers=headers, json=payload).status_code, equal_to(422))
        assert_that(context.client.get(url, headers=headers).json()["updated_at"], is_(None))


def test_platform_workflow_setting_audits_changes_once_and_blocks_read_only_keys() -> None:
    from sqlmodel import Session, select

    from api.domains.events.models import EventDelivery, EventScope, OutboxMessage
    from api.domains.events.processor import EventDeliveryProcessor
    from api.domains.events.repository import OutboxMessageRepository
    from api.domains.events.security_audit import SecurityAuditRecord
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN) as context:
        headers = platform_admin_headers(context)
        url = "/api/v1/platform/settings/workflows"
        for _ in range(2):
            assert_that(
                context.client.put(url, headers=headers, json={"authoring_enabled": False}).status_code, equal_to(200)
            )
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            events = session.exec(
                select(OutboxMessage).where(OutboxMessage.event_name == "platform.workflow_authoring.changed")
            ).all()
            assert_that(events, has_length(1))
            assert_that(events[0].event_scope, equal_to(EventScope.PLATFORM))
            assert_that(events[0].organization_id, is_(None))
            assert_that(events[0].payload["previous"], is_(True))
            assert_that(events[0].payload["current"], is_(False))
            delivery = session.exec(select(EventDelivery).where(EventDelivery.event_id == events[0].event_id)).one()
            # Projection tests drive delivery explicitly; CI has no Redis broker.
            context.injector.get(OutboxMessageRepository).mark_delivery_enqueued(delivery.id)
            assert_that(context.injector.get(EventDeliveryProcessor).process(delivery.id), is_(True))
            audits = session.exec(
                select(SecurityAuditRecord).where(SecurityAuditRecord.action == "platform.workflow_authoring.changed")
            ).all()
            assert_that(audits, has_length(1))
        token = context.client.post(
            "/api/v1/auth/me/api-keys", headers=headers, json={"name": "read-only platform", "access_mode": "READ_ONLY"}
        ).json()["token"]
        read_headers = {"Authorization": f"Bearer {token}"}
        assert_that(context.client.get(url, headers=read_headers).status_code, equal_to(200))
        assert_that(
            context.client.put(url, headers=read_headers, json={"authoring_enabled": True}).status_code, equal_to(403)
        )


def test_platform_workflow_setting_migration_preserves_saved_workflows_and_rolls_back() -> None:
    from alembic import command
    from sqlalchemy import inspect

    from api.tests.conftest import config
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN) as context:
        saved = create(context)
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        command.downgrade(config, "a38801c6e001")
        try:
            assert_that("platform_workflow_settings" in inspect(engine).get_table_names(), is_(False))
        finally:
            command.upgrade(config, "head")
        url = "/api/v1/platform/settings/workflows"
        headers = platform_admin_headers(context)
        assert_that(context.client.get(url, headers=headers).json()["updated_at"], is_(None))
        assert_that(
            context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context)).status_code,
            equal_to(200),
        )
        context.client.put(url, headers=headers, json={"authoring_enabled": False})
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO platform_workflow_settings (id, authoring_enabled, updated_at) VALUES (2, true, now())"
                )
            )


def test_saving_current_workflow_default_persists_choice_without_a_change_event() -> None:
    from sqlmodel import Session, select

    from api.domains.events.models import OutboxMessage
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN[:-1]) as context:
        headers = platform_admin_headers(context)
        url = "/api/v1/platform/settings/workflows"
        response = context.client.put(url, headers=headers, json={"authoring_enabled": False})
        assert_that(response.status_code, equal_to(200))
        assert_that(context.client.get(url, headers=headers).json()["authoring_enabled"], is_(False))
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(
                session.exec(
                    select(OutboxMessage).where(OutboxMessage.event_name == "platform.workflow_authoring.changed")
                ).all(),
                has_length(0),
            )


def test_workflow_setting_is_not_committed_if_audit_staging_fails(monkeypatch) -> None:
    from api.domains.events.repository import OutboxMessageRepository
    from api.tests.helpers.workflows import platform_admin_headers

    with given(_GIVEN) as context:
        headers = platform_admin_headers(context)
        url = "/api/v1/platform/settings/workflows"

        before = context.client.get(url, headers=headers).json()

        def fail_stage(**kwargs):
            raise RuntimeError("audit staging unavailable")

        monkeypatch.setattr(context.injector.get(OutboxMessageRepository), "stage", fail_stage)
        with pytest.raises(RuntimeError, match="audit staging unavailable"):
            context.client.put(url, headers=headers, json={"authoring_enabled": False})
        response = context.client.get(url, headers=headers)
        assert_that(response.json()["authoring_enabled"], is_(True))
        assert_that(response.json(), equal_to(before))
