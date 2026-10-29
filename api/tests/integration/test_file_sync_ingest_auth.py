from datetime import UTC, datetime

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to
from sqlmodel import Session

from api.domains.agents.models import Agent, AgentType
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncAgentFolder, SyncFolderStatus
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.sync_provider.repository import SyncProviderRepository
from api.infrastructure.crypto import encrypt_token
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_ingest_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.file_sync_provider import TestDriveModule, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.sync_provider import OTHER_DRIVE

_KEY = "agent-ingest-key"
_OTHER_KEY = "other-agent-ingest-key"
_SHA = "0" * 64

_BASE = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[TestDriveModule()]),
    database_repo_is_ready(),
    prepare_ingest_server(),
    there_is_an_organization(),
]


def _with_key(context, agent: Agent, key: str) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(Agent, agent.id)
        assert row is not None
        row.ingest_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        session.add(row)
        session.commit()


def _agent(context, name: str = "Sales Bot", key: str = _KEY, agent_type: AgentType = AgentType.OPENCLAW) -> Agent:
    there_is_an_agent(name=name, agent_type=agent_type)(context)
    _with_key(context, context.agent, key)
    return context.agent


def _synced(context) -> None:
    context.injector.get(FileSyncEngine).reconcile_folders(context.connection)


def _report(context, agent: Agent, *, key: str = _KEY, entries: list[dict] | None = None, complete: bool = True):
    body = {
        "complete": complete,
        "entries": entries if entries is not None else [{"path": "workspace/notes.md", "size": 5, "sha256": _SHA}],
    }
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/changes",
        json=body,
        headers={"Authorization": f"Bearer {key}"},
    )


def _set_folder_status(context, agent: Agent, folder_status: SyncFolderStatus) -> None:
    with Session(context.postgres_delegate.engine) as session:
        folder = next(
            f for f in context.injector.get(FileSyncRepository).folders(context.connection.id) if f.agent_id == agent.id
        )
        row = session.get(SyncAgentFolder, folder.id)
        assert row is not None
        row.status = folder_status
        session.add(row)
        session.commit()


def test_a_ready_agent_reports_its_files():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_a_hermes_agent_reports_paths_in_its_own_layout():
    with given(_BASE) as context:
        agent = _agent(context, agent_type=AgentType.HERMES)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(
            context,
            agent,
            entries=[
                {"path": "memories/USER.md", "size": 1, "sha256": _SHA},
                {"path": "SOUL.md", "size": 1, "sha256": _SHA},
                {"path": "workspace/skills/jira/SKILL.md", "size": 1, "sha256": _SHA},
            ],
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


@pytest.mark.parametrize("key", ["wrong-key", ""])
def test_a_wrong_key_is_unauthorised(key):
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(context, agent, key=key)

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_unknown_agent_is_unauthorised_not_reported_missing():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)
        unknown = Agent.model_validate({**agent.model_dump(), "id": agent.organization_id})

        response = _report(context, unknown)

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_agent_without_an_ingest_key_is_unauthorised():
    with given(_BASE) as context:
        there_is_an_agent(name="Never Started")(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(context, context.agent)

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_deleted_agent_with_its_last_key_is_not_found():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(Agent, agent.id)
            assert row is not None
            row.deleted_at = datetime.now(UTC)
            session.add(row)
            session.commit()

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_organization_without_a_connection_is_a_conflict():
    with given(_BASE) as context:
        agent = _agent(context)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_connection_whose_provider_has_no_file_sync_is_a_conflict():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection(provider_key=OTHER_DRIVE)(context)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_disconnected_organization_is_a_conflict():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)
        context.injector.get(SyncProviderRepository).mark_disconnected(context.connection.id)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_an_agent_whose_folder_the_engine_has_not_made_yet_is_told_to_come_back():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("not ready"))


def test_a_key_with_characters_outside_ascii_is_refused_not_a_crash():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = context.ingest_client.post(
            f"/ingest/v1/agents/{agent.id}/file-sync/changes",
            json={"complete": False, "entries": []},
            headers={"Authorization": "Bearer ključ".encode()},
        )

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_folder_not_yet_created_at_the_provider_is_a_conflict():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        context.injector.get(FileSyncRepository).reserve_folder(context.connection, agent.id, "Sales Bot")

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_folder_with_sync_turned_off_is_a_conflict():
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)
        _set_folder_status(context, agent, SyncFolderStatus.DISABLED)

        response = _report(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "aai-cli/key",
        "openclaw.json",
        "workspace/../openclaw.json",
        "/home/node/.openclaw/workspace/notes.md",
        "workspace\\notes.md",
        "workspace/node_modules/x/index.js",
        "_Not synced/notes.md",
        "workspace/café.md",
    ],
)
def test_a_path_the_rules_do_not_allow_is_a_bad_request_naming_it(path):
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(
            context,
            agent,
            entries=[{"path": "workspace/ok.md", "size": 1, "sha256": _SHA}, {"path": path, "size": 1, "sha256": _SHA}],
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], contains_string(repr(path)))


def test_a_hermes_path_is_judged_by_the_hermes_rules():
    with given(_BASE) as context:
        agent = _agent(context, agent_type=AgentType.HERMES)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(context, agent, entries=[{"path": "config.yaml", "size": 1, "sha256": _SHA}])

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@pytest.mark.parametrize(
    "entries",
    [
        [{"path": "workspace/a.md", "size": 1, "sha256": _SHA}] * 10_001,
        [{"path": "workspace/" + "a" * 1100, "size": 1, "sha256": _SHA}],
        [{"path": "workspace/a.md", "size": -1, "sha256": _SHA}],
        [{"path": "workspace/a.md", "size": 1, "sha256": "not-a-hash"}],
        [{"path": "", "size": 1, "sha256": _SHA}],
    ],
)
def test_an_oversized_or_malformed_report_is_refused(entries):
    with given(_BASE) as context:
        agent = _agent(context)
        there_is_a_sync_connection()(context)
        _synced(context)

        response = _report(context, agent, entries=entries)

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_one_agents_key_never_opens_another_agents_sync():
    with given(_BASE) as context:
        ours = _agent(context, name="Ours", key=_KEY)
        theirs = _agent(context, name="Theirs", key=_OTHER_KEY)
        there_is_a_sync_connection()(context)
        _synced(context)

        assert_that(_report(context, theirs, key=_KEY).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        assert_that(_report(context, ours, key=_OTHER_KEY).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        assert_that(_report(context, ours, key=_KEY).status_code, equal_to(status.HTTP_200_OK))


def test_an_agent_is_judged_by_its_own_organizations_connection_only():
    with given(_BASE) as context:
        connected = _agent(context, name="Connected", key=_KEY)
        there_is_a_sync_connection()(context)
        _synced(context)
        there_is_an_organization(name="Other Org")(context)
        unconnected = _agent(context, name="Elsewhere", key=_OTHER_KEY)

        assert_that(_report(context, connected, key=_KEY).status_code, equal_to(status.HTTP_200_OK))
        assert_that(_report(context, unconnected, key=_OTHER_KEY).status_code, equal_to(status.HTTP_409_CONFLICT))
