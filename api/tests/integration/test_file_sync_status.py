"""An Agent's File Sync status, as its page shows it.

Reading it needs `activity.read`. The state is one of: not connected, turned off, setting up, throttled,
waiting for the next restart, not syncing, or synced.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_entries
from sqlmodel import Session

from api.domains.agents.models import Agent, AgentStatus
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncActivity, SyncActivityKind, SyncAgentFolder, SyncFolderStatus
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.repository import SyncProviderRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.agent_memory import signed_in_as
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.file_sync_provider import TEST_DRIVE, TestDriveModule, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.sync_provider import OTHER_DRIVE

_TEST_DRIVE = {"key": TEST_DRIVE, "display_name": "Test Drive"}


def _given(*steps, agent_status: AgentStatus = AgentStatus.RUNNING):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[TestDriveModule(), MockK8sModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        there_is_an_agent(name="Sales Bot", status=agent_status),
        *steps,
    ]


def an_agent_folder():
    def step(context):
        there_is_a_sync_connection()(context)
        context.injector.get(FileSyncEngine).reconcile_folders(context.connection)

    return step


def last_contact(ago: timedelta):
    def step(context):
        _update(context, SyncAgentFolder, _folder(context).id, last_contact_at=datetime.now(UTC) - ago)

    return step


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(context, agent_id: UUID) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{agent_id}/file-sync"


def _read(context, agent_id: UUID | None = None, headers: dict[str, str] | None = None):
    return context.client.get(
        _url(context, agent_id or context.agent.id), headers=_auth(context) if headers is None else headers
    )


def _folder(context) -> SyncAgentFolder:
    return next(
        folder
        for folder in context.injector.get(FileSyncRepository).folders(context.connection.id)
        if folder.agent_id == context.agent.id
    )


def _folder_url(context) -> str:
    url = _folder(context).folder_web_url
    assert url is not None
    return url


def _update(context, model, row_id: UUID, **fields) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(model, row_id)
        assert row is not None
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()


def _state(response) -> str:
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    return response.json()["state"]


def _custom_access_without_activity(context) -> None:
    repository = context.injector.get(PostgresRepositoryDelegate)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
    repository.save(role)
    repository.save(
        AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ])
    )
    there_is_agent_access(access_role_id=role.id)(context)


# --- Who may read it -------------------------------------------------------------------


def test_an_agent_viewer_can_read_the_status():
    with given(
        _given(signed_in_as(OrganizationRole.MEMBER), there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID))
    ) as context:
        with when("an Agent Viewer reads the File Sync status"):
            response = _read(context)

        with then("they are allowed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_a_role_without_activity_read_is_forbidden():
    with given(_given(signed_in_as(OrganizationRole.MEMBER))) as context:
        _custom_access_without_activity(context)

        with when("a Member who can see the Agent but not its activity reads the status"):
            response = _read(context)

        with then("the request is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_without_access_cannot_see_the_agent():
    with given(_given(signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member with no access to the Agent reads the status"):
            response = _read(context)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


@pytest.mark.parametrize("target", ["missing", "deleted", "foreign"])
def test_an_absent_or_foreign_agent_is_not_found(target):
    with given(_given()) as context:
        there_is_an_agent(name="Retired", deleted=True)(context)
        deleted_agent_id = context.agent.id
        there_is_an_agent_in_another_org()(context)
        agent_id = {"missing": uuid7(), "deleted": deleted_agent_id, "foreign": context.other_org_agent.id}[target]

        with when("the Owner reads the status of an unavailable Agent"):
            response = _read(context, agent_id=agent_id)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_reading_the_status_requires_authentication():
    with given(_given()) as context:
        with when("an unauthenticated caller reads the status"):
            response = _read(context, headers={})

        with then("the request is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_read_only_api_key_can_read_the_status():
    with given(_given()) as context:
        key = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(context),
        ).json()["token"]

        with when("a read-only API key reads the status"):
            response = _read(context, headers={"Authorization": f"Bearer {key}"})

        with then("it is allowed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


# --- What it says ----------------------------------------------------------------------


def test_without_a_connection_the_agent_is_not_connected():
    with given(_given()) as context:
        with when("the Owner reads the status of an Organization with no Sync Provider"):
            response = _read(context)

        with then("it is not connected, with nothing to open"):
            assert_that(
                response.json(),
                equal_to(
                    {
                        "enabled": True,
                        "state": "not_connected",
                        "provider": None,
                        "folder_url": None,
                        "last_contact_at": None,
                        "retry_at": None,
                    }
                ),
            )


def test_a_connection_still_being_set_up_is_not_connected():
    with given(_given()) as context:
        context.injector.get(SyncProviderRepository).create_pending(
            context.organization.id,
            TEST_DRIVE,
            schema_version=1,
            account_id="test-drive-account",
            connected_by_user_id=context.user.id,
            credentials_encrypted="encrypted-token",
            pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        assert_that(_state(_read(context)), equal_to("not_connected"))


def test_a_provider_without_file_sync_is_not_connected():
    with given(_given(lambda context: there_is_a_sync_connection(provider_key=OTHER_DRIVE)(context))) as context:
        assert_that(_state(_read(context)), equal_to("not_connected"))


def test_a_provider_no_longer_on_this_server_is_not_connected():
    with given(_given(an_agent_folder())) as context:
        _update(context, SyncProviderConnection, context.connection.id, provider_key="retiredprovider")

        assert_that(_state(_read(context)), equal_to("not_connected"))


def test_a_switched_off_agent_is_turned_off_and_its_folder_can_still_be_opened():
    with given(_given(an_agent_folder())) as context:
        _update(context, Agent, context.agent.id, file_sync_enabled=False)

        response = _read(context)

        assert_that(
            response.json(),
            has_entries(enabled=False, state="turned_off", provider=_TEST_DRIVE, folder_url=_folder_url(context)),
        )


def test_an_agent_switched_off_before_connecting_reports_its_switch():
    with given(_given()) as context:
        _update(context, Agent, context.agent.id, file_sync_enabled=False)

        assert_that(_read(context).json(), has_entries(enabled=False, state="not_connected"))


def test_an_agent_the_engine_has_not_reached_is_setting_up():
    with given(_given(lambda context: there_is_a_sync_connection()(context))) as context:
        assert_that(_read(context).json(), has_entries(state="setting_up", provider=_TEST_DRIVE, folder_url=None))


def test_a_folder_not_yet_created_at_the_provider_is_setting_up():
    with given(_given(lambda context: there_is_a_sync_connection()(context))) as context:
        context.injector.get(FileSyncRepository).reserve_folder(context.connection, context.agent.id, "Sales Bot")

        assert_that(_state(_read(context)), equal_to("setting_up"))


def test_a_folder_still_disabled_after_sync_is_turned_on_is_setting_up():
    with given(_given(an_agent_folder())) as context:
        _update(context, SyncAgentFolder, _folder(context).id, status=SyncFolderStatus.DISABLED)

        assert_that(_read(context).json(), has_entries(enabled=True, state="setting_up"))


def test_a_throttled_connection_says_when_syncing_resumes():
    with given(_given(an_agent_folder(), last_contact(timedelta(seconds=5)))) as context:
        resumes = datetime.now(UTC) + timedelta(minutes=2)
        _update(context, SyncProviderConnection, context.connection.id, sync_retry_at=resumes)

        response = _read(context)

        assert_that(response.json(), has_entries(state="throttled"))
        assert_that(datetime.fromisoformat(response.json()["retry_at"]), equal_to(resumes))


def test_a_throttling_wait_already_over_is_not_reported():
    with given(_given(an_agent_folder(), last_contact(timedelta(seconds=5)))) as context:
        _update(
            context,
            SyncProviderConnection,
            context.connection.id,
            sync_retry_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        assert_that(_read(context).json(), has_entries(state="synced", retry_at=None))


def test_a_pod_that_never_made_contact_starts_syncing_after_the_next_restart():
    with given(_given(an_agent_folder())) as context:
        response = _read(context)

        assert_that(
            response.json(),
            has_entries(
                state="waiting_for_restart",
                provider=_TEST_DRIVE,
                folder_url=_folder_url(context),
                last_contact_at=None,
            ),
        )


def test_a_pod_in_contact_is_synced():
    with given(_given(an_agent_folder(), last_contact(timedelta(seconds=5)))) as context:
        response = _read(context)

        assert_that(response.json(), has_entries(state="synced", folder_url=_folder_url(context)))
        assert_that(
            datetime.fromisoformat(response.json()["last_contact_at"]), equal_to(_folder(context).last_contact_at)
        )


def test_a_running_agent_just_inside_ten_minutes_is_still_synced():
    with given(_given(an_agent_folder(), last_contact(timedelta(minutes=9, seconds=50)))) as context:
        assert_that(_state(_read(context)), equal_to("synced"))


def test_a_running_agent_out_of_contact_for_over_ten_minutes_is_not_syncing():
    with given(_given(an_agent_folder(), last_contact(timedelta(minutes=10, seconds=10)))) as context:
        assert_that(_state(_read(context)), equal_to("not_syncing"))


def test_an_agent_in_error_out_of_contact_is_not_syncing():
    with given(_given(an_agent_folder(), last_contact(timedelta(hours=1)), agent_status=AgentStatus.ERROR)) as context:
        assert_that(_state(_read(context)), equal_to("not_syncing"))


def test_a_stopped_agent_out_of_contact_is_still_synced():
    with given(_given(an_agent_folder(), last_contact(timedelta(days=2)), agent_status=AgentStatus.STOPPED)) as context:
        assert_that(_state(_read(context)), equal_to("synced"))


# --- What happened ---------------------------------------------------------------------


def _read_activity(context, agent_id: UUID | None = None, params: dict | None = None, headers: dict | None = None):
    return context.client.get(
        f"{_url(context, agent_id or context.agent.id)}/activity",
        params=params,
        headers=_auth(context) if headers is None else headers,
    )


def _record(
    context,
    kind: SyncActivityKind,
    path: str | None,
    occurred_at: datetime,
    agent: Agent | None = None,
    detail: str | None = None,
) -> SyncActivity:
    row = SyncActivity(
        organization_id=context.organization.id,
        agent_id=(agent or context.agent).id,
        folder_id=None,
        kind=kind,
        path=path,
        detail=detail,
        occurred_at=occurred_at,
    )
    context.injector.get(PostgresRepositoryDelegate).save(row)
    return row


def _paths(response) -> list[str | None]:
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    return [item["path"] for item in response.json()["items"]]


def test_an_agent_viewer_can_read_the_history():
    with given(
        _given(signed_in_as(OrganizationRole.MEMBER), there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID))
    ) as context:
        with when("an Agent Viewer reads what File Sync did"):
            response = _read_activity(context)

        with then("they are allowed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_the_history_needs_activity_read():
    with given(_given(signed_in_as(OrganizationRole.MEMBER))) as context:
        _custom_access_without_activity(context)

        with when("a Member who can see the Agent but not its activity reads the history"):
            response = _read_activity(context)

        with then("the request is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_the_history_of_an_agent_a_member_cannot_see_is_concealed():
    with given(_given(signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member with no access to the Agent reads its history"):
            response = _read_activity(context)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


@pytest.mark.parametrize("target", ["missing", "deleted", "foreign"])
def test_the_history_of_an_absent_or_foreign_agent_is_not_found(target):
    with given(_given()) as context:
        there_is_an_agent(name="Retired", deleted=True)(context)
        deleted_agent_id = context.agent.id
        there_is_an_agent_in_another_org()(context)
        agent_id = {"missing": uuid7(), "deleted": deleted_agent_id, "foreign": context.other_org_agent.id}[target]

        with when("the Owner reads the history of an unavailable Agent"):
            response = _read_activity(context, agent_id=agent_id)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_reading_the_history_requires_authentication():
    with given(_given()) as context:
        with when("an unauthenticated caller reads the history"):
            response = _read_activity(context, headers={})

        with then("the request is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_the_history_is_newest_first():
    with given(_given()) as context:
        now = datetime.now(UTC)
        _record(context, SyncActivityKind.EDIT_UNDONE, "workspace/AGENTS.md", now - timedelta(hours=2))
        _record(context, SyncActivityKind.MOVED_NOT_SYNCED, "workspace/budget.xlsx", now)
        _record(context, SyncActivityKind.SKIPPED_TOO_LARGE, "workspace/video.mp4", now - timedelta(hours=1))

        response = _read_activity(context)

        assert_that(_paths(response), equal_to(["workspace/budget.xlsx", "workspace/video.mp4", "workspace/AGENTS.md"]))


def test_entries_at_the_same_moment_keep_a_stable_order():
    with given(_given()) as context:
        moment = datetime.now(UTC)
        first = _record(context, SyncActivityKind.RESTORED, "workspace/a.md", moment)
        second = _record(context, SyncActivityKind.RESTORED, "workspace/b.md", moment)

        response = _read_activity(context)

        expected = [row.path for row in sorted((first, second), key=lambda row: row.id, reverse=True)]
        assert_that(_paths(response), equal_to(expected))


def test_the_history_is_paged():
    with given(_given()) as context:
        now = datetime.now(UTC)
        for minutes in range(3):
            _record(context, SyncActivityKind.RESTORED, f"workspace/{minutes}.md", now - timedelta(minutes=minutes))

        first = _read_activity(context, params={"page": 1, "page_size": 2})
        second = _read_activity(context, params={"page": 2, "page_size": 2})

        assert_that(first.json(), has_entries(page=1, page_size=2, total=3))
        assert_that(_paths(first), equal_to(["workspace/0.md", "workspace/1.md"]))
        assert_that(_paths(second), equal_to(["workspace/2.md"]))


def test_a_page_larger_than_a_hundred_is_refused():
    with given(_given()) as context:
        response = _read_activity(context, params={"page_size": 101})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_the_history_holds_only_this_agents_entries():
    with given(_given()) as context:
        sales = context.agent
        there_is_an_agent(name="Support")(context)
        support = context.agent
        now = datetime.now(UTC)
        _record(context, SyncActivityKind.RESTORED, "workspace/sales.md", now, agent=sales)
        _record(context, SyncActivityKind.RESTORED, "workspace/support.md", now, agent=support)

        response = _read_activity(context, agent_id=sales.id)

        assert_that(_paths(response), equal_to(["workspace/sales.md"]))
        assert_that(response.json()["total"], equal_to(1))


def test_entries_from_before_a_disconnect_are_kept():
    with given(_given()) as context:
        _record(context, SyncActivityKind.CONFLICT_AGENT_WON, "workspace/notes.md", datetime.now(UTC))

        assert_that(_paths(_read_activity(context)), equal_to(["workspace/notes.md"]))


def test_an_entry_shows_what_happened_and_when_but_never_its_internal_detail():
    with given(_given()) as context:
        row = _record(context, SyncActivityKind.SKIPPED_NAME, "workspace/a:b.md", datetime.now(UTC), detail="0" * 64)

        response = _read_activity(context)

        item = response.json()["items"][0]
        assert_that(set(item), equal_to({"id", "kind", "path", "occurred_at"}))
        assert_that(
            (item["id"], item["kind"], datetime.fromisoformat(item["occurred_at"])),
            equal_to((str(row.id), "skipped_name", row.occurred_at)),
        )


def test_a_folder_entry_has_no_path():
    with given(_given()) as context:
        _record(context, SyncActivityKind.FOLDER_RESTORED, None, datetime.now(UTC))

        assert_that(_paths(_read_activity(context)), equal_to([None]))
