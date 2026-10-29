"""Turning File Sync off and on for one Agent.

The switch needs `agent.update`. Turning it off keeps the Agent's folder at the provider but marks it
`disabled`; turning it on makes the folder `active` again and asks the Sync Engine to re-check it.
"""

from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, empty, equal_to, has_entries, none, not_none
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.events.models import OutboxMessage
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncAgentFolder, SyncFolderStatus
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
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
from api.tests.steps.file_sync_provider import TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

FILE_SYNC_ENABLED = "agent.file_sync.enabled"
FILE_SYNC_DISABLED = "agent.file_sync.disabled"


def _given(*steps):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[TestDriveModule(), MockK8sModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        there_is_an_agent(name="Sales Bot"),
        *steps,
    ]


def an_agent_folder():
    def step(context):
        there_is_a_sync_connection()(context)
        context.injector.get(FileSyncEngine).reconcile_folders(context.connection)

    return step


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(context, agent_id: UUID) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{agent_id}/file-sync"


def _switch(context, enabled: bool, agent_id: UUID | None = None, headers: dict[str, str] | None = None):
    return context.client.put(
        _url(context, agent_id or context.agent.id),
        json={"enabled": enabled},
        headers=_auth(context) if headers is None else headers,
    )


def _stored_agent(context, agent_id: UUID) -> Agent:
    return context.injector.get(PostgresRepositoryDelegate).find_by_id(Agent, agent_id)


def _folders(context, agent_id: UUID) -> list[SyncAgentFolder]:
    with Session(context.postgres_delegate.engine) as session:
        return list(session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.agent_id) == agent_id)))


def _folder(context, agent_id: UUID) -> SyncAgentFolder:
    folders = _folders(context, agent_id)
    assert_that(len(folders), equal_to(1))
    return folders[0]


def _event_names(context) -> list[str]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message.event_name for message in sorted(messages, key=lambda message: message.occurred_at)]


def test_the_owner_turns_file_sync_off():
    with given(_given()) as context:
        with when("the Organization Owner turns file sync off"):
            response = _switch(context, False)

        with then("the switch is off"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to({"agent_id": str(context.agent.id), "enabled": False}))
            assert_that(_stored_agent(context, context.agent.id).file_sync_enabled, equal_to(False))


def test_an_admin_turns_file_sync_off():
    with given(_given(signed_in_as(OrganizationRole.ADMIN))) as context:
        with when("an Organization Admin turns file sync off"):
            response = _switch(context, False)

        with then("the switch is off"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_stored_agent(context, context.agent.id).file_sync_enabled, equal_to(False))


@pytest.mark.parametrize(
    "role_id, expected",
    [
        (AGENT_OWNER_ROLE_ID, status.HTTP_200_OK),
        (AGENT_EDITOR_ROLE_ID, status.HTTP_200_OK),
        (AGENT_VIEWER_ROLE_ID, status.HTTP_403_FORBIDDEN),
    ],
)
def test_agent_access_decides_who_may_switch(role_id, expected):
    with given(_given(signed_in_as(OrganizationRole.MEMBER), there_is_agent_access(access_role_id=role_id))) as context:
        with when("a Member with explicit Agent Access turns file sync off"):
            response = _switch(context, False)

        with then("agent.update decides, and a refusal changes nothing"):
            assert_that(response.status_code, equal_to(expected))
            assert_that(
                _stored_agent(context, context.agent.id).file_sync_enabled,
                equal_to(expected != status.HTTP_200_OK),
            )


def test_a_member_without_access_cannot_see_the_agent():
    with given(_given(signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member with no access to the Agent turns file sync off"):
            response = _switch(context, False)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_stored_agent(context, context.agent.id).file_sync_enabled, equal_to(True))


@pytest.mark.parametrize("target", ["missing", "deleted", "foreign"])
def test_an_absent_or_foreign_agent_is_not_found(target):
    with given(_given()) as context:
        there_is_an_agent(name="Retired", deleted=True)(context)
        deleted_agent_id = context.agent.id
        there_is_an_agent_in_another_org()(context)
        agent_id = {"missing": uuid7(), "deleted": deleted_agent_id, "foreign": context.other_org_agent.id}[target]

        with when("the Owner turns file sync off for an unavailable Agent"):
            response = _switch(context, False, agent_id=agent_id)

        with then("the Agent is concealed and nothing is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_event_names(context), empty())


def test_a_read_only_api_key_cannot_switch():
    with given(_given()) as context:
        key = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(context),
        ).json()["token"]

        with when("a read-only API key turns file sync off"):
            response = _switch(context, False, headers={"Authorization": f"Bearer {key}"})

        with then("it is refused and the switch stays on"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_stored_agent(context, context.agent.id).file_sync_enabled, equal_to(True))


def test_switching_requires_authentication():
    with given(_given()) as context:
        with when("an unauthenticated caller turns file sync off"):
            response = _switch(context, False, headers={})

        with then("the request is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


@pytest.mark.parametrize("payload", [{}, {"enabled": "maybe"}, {"enabled": False, "folder_url": "x"}])
def test_a_malformed_request_is_refused(payload):
    with given(_given()) as context:
        with when("the Owner sends a malformed switch request"):
            response = context.client.put(_url(context, context.agent.id), json=payload, headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_turning_sync_off_keeps_the_folder_but_disables_it():
    with given(_given(an_agent_folder())) as context:
        with when("the Owner turns file sync off"):
            response = _switch(context, False)

        with then("the folder is disabled in the same request and stays at the provider"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            folder = _folder(context, context.agent.id)
            assert_that(folder.status, equal_to(SyncFolderStatus.DISABLED))
            assert folder.folder_item_id is not None
            assert_that(fake_drive(context).nodes[folder.folder_item_id].deleted, equal_to(False))


def test_turning_sync_back_on_resumes_the_folder_and_asks_for_a_re_check():
    with given(_given(an_agent_folder())) as context:
        _switch(context, False)

        with when("the Owner turns file sync back on"):
            response = _switch(context, True)

        with then("the folder is active and a re-check is requested"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            folder = _folder(context, context.agent.id)
            assert_that(folder.status, equal_to(SyncFolderStatus.ACTIVE))
            assert_that(folder.resync_requested_at, not_none())


def test_without_a_folder_only_the_switch_changes():
    with given(_given()) as context:
        with when("the Owner turns file sync off before any folder exists"):
            response = _switch(context, False)

        with then("the switch is off and no folder is made"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_stored_agent(context, context.agent.id).file_sync_enabled, equal_to(False))
            assert_that(_folders(context, context.agent.id), empty())


def test_switching_off_and_on_is_audited():
    with given(_given()) as context:
        _switch(context, False)

        with when("the Owner turns file sync back on"):
            _switch(context, True)

        with then("both changes are audited, in order"):
            assert_that(_event_names(context), contains_exactly(FILE_SYNC_DISABLED, FILE_SYNC_ENABLED))


def test_the_audit_names_the_agent_and_who_switched():
    with given(_given()) as context:
        with when("the Owner turns file sync off"):
            _switch(context, False)

        with then("the event is scoped to this Organization and Agent"):
            messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
            assert_that(len(messages), equal_to(1))
            assert_that(
                messages[0].payload,
                has_entries(
                    organization_id=str(context.organization.id),
                    agent_id=str(context.agent.id),
                    subject_display="Sales Bot",
                ),
            )


def test_repeating_the_current_setting_records_nothing():
    with given(_given(an_agent_folder())) as context:
        with when("the Owner turns file sync on while it is already on"):
            response = _switch(context, True)

        with then("the request succeeds without an audit record or a re-check"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to({"agent_id": str(context.agent.id), "enabled": True}))
            assert_that(_event_names(context), empty())
            assert_that(_folder(context, context.agent.id).resync_requested_at, none())


def test_switching_one_agent_leaves_other_agents_alone():
    with given(_given()) as context:
        first = context.agent
        there_is_an_agent(name="Support")(context)
        second = context.agent
        an_agent_folder()(context)

        with when("the Owner turns file sync off for one Agent"):
            _switch(context, False, agent_id=first.id)

        with then("the other Agent and its folder are unchanged"):
            assert_that(_stored_agent(context, second.id).file_sync_enabled, equal_to(True))
            assert_that(_folder(context, second.id).status, equal_to(SyncFolderStatus.ACTIVE))
