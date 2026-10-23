import threading
import time
from datetime import UTC, datetime

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_length
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.file_sync import service as file_sync_service
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncActivity, SyncActivityKind, SyncAgentFolder, SyncFile
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.sync_provider.models import SyncProviderConnection, SyncProviderStatus
from api.domains.sync_provider.plugins.base import ProviderUnavailable, RemoteItemMissing
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.file_sync_ingest import SHA_A
from api.tests.steps.file_sync_provider import TEST_DRIVE, TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[TestDriveModule(), MockK8sModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/sync-providers/{TEST_DRIVE}/connection"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _disconnect(context):
    response = context.client.get(
        f"{_base(context)}/authorize-url", params={"purpose": "disconnect"}, headers=_auth(context)
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    state = response.json()["authorize_url"].split("state=", 1)[1]
    return context.client.post(
        f"{_base(context)}/disconnect", json={"code": "the-code", "state": state}, headers=_auth(context)
    )


def _synced_agents(context) -> tuple[Agent, Agent]:
    there_is_an_agent(name="Sales Bot")(context)
    sales = context.agent
    there_is_an_agent(name="Support")(context)
    support = context.agent
    there_is_a_sync_connection()(context)
    context.injector.get(FileSyncEngine).reconcile_folders(context.connection)
    return sales, support


def _folders(context) -> list[SyncAgentFolder]:
    with Session(context.postgres_delegate.engine) as session:
        return list(
            session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.connection_id) == context.connection.id))
        )


def _live_children(context) -> list[str]:
    root_id = context.sync_root.folder_id
    return sorted(
        node.name for node in fake_drive(context).nodes.values() if node.parent_id == root_id and not node.deleted
    )


def _connection_status(context) -> SyncProviderStatus:
    with Session(context.postgres_delegate.engine) as session:
        connection = session.get(SyncProviderConnection, context.connection.id)
        assert connection is not None
        return connection.status


def _record_revokes(context, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    plugin = fake_drive(context)
    revokes: list[str] = []

    def revoke(token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        plugin.calls.append("revoke")
        revokes.append(token)

    monkeypatch.setattr(plugin, "revoke", revoke)
    return revokes


def test_disconnecting_deletes_every_agent_folder_first_and_keeps_the_root(monkeypatch: pytest.MonkeyPatch):
    with given(_GIVEN) as context:
        sales, _ = _synced_agents(context)
        repository = context.injector.get(FileSyncRepository)
        repository.retire_folders([folder.id for folder in _folders(context) if folder.agent_id == sales.id])
        folder = next(folder for folder in _folders(context) if folder.agent_id != sales.id)
        repository.start_upload(folder.id, "workspace/notes.md", sha256=SHA_A, size=5, now=datetime.now(UTC))
        repository.record_activity(folder, SyncActivityKind.RESTORED, "workspace/notes.md", datetime.now(UTC))
        _record_revokes(context, monkeypatch)
        fake_drive(context).calls.clear()

        with when("an Owner signs in again and disconnects"):
            response = _disconnect(context)

        with then("every Agent folder, a retired one still waiting to be deleted too, goes before the revoke"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(_live_children(context), equal_to([]))
            assert_that(fake_drive(context).calls, equal_to(["delete_item", "delete_item", "revoke"]))
            assert_that(fake_drive(context).nodes[context.sync_root.folder_id].deleted, equal_to(False))

        with then("the folder and file rows are gone, the activity stays, and the connection is closed"):
            assert_that(_folders(context), equal_to([]))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(list(session.exec(select(SyncFile))), equal_to([]))
                activity = list(session.exec(select(SyncActivity)))
            assert_that([(entry.kind, entry.folder_id) for entry in activity], equal_to([("restored", None)]))
            assert_that(_connection_status(context), equal_to(SyncProviderStatus.DISCONNECTED))

        with then("the Agents' pods and volumes are not touched"):
            assert_that(context.injector.get(KubernetesClient).mock_calls, equal_to([]))


def test_the_engine_creates_no_folders_after_a_disconnect(monkeypatch: pytest.MonkeyPatch):
    with given(_GIVEN) as context:
        _synced_agents(context)
        _record_revokes(context, monkeypatch)
        assert_that(_disconnect(context).status_code, equal_to(status.HTTP_200_OK))

        context.injector.get(FileSyncEngine).run_pass(datetime.now(UTC))

        assert_that(_live_children(context), equal_to([]))
        assert_that(_folders(context), equal_to([]))


def test_a_folder_already_gone_at_the_provider_does_not_stop_the_disconnect(monkeypatch: pytest.MonkeyPatch):
    with given(_GIVEN) as context:
        _synced_agents(context)
        revokes = _record_revokes(context, monkeypatch)
        plugin = fake_drive(context)
        delete = plugin.delete_item
        gone = _folders(context)[0].folder_item_id

        def delete_item(root, *, item_id: str) -> None:
            if item_id == gone:
                raise RemoteItemMissing(item_id)
            delete(root, item_id=item_id)

        monkeypatch.setattr(plugin, "delete_item", delete_item)

        response = _disconnect(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(revokes, has_length(1))
        assert_that(_folders(context), equal_to([]))
        assert_that(_connection_status(context), equal_to(SyncProviderStatus.DISCONNECTED))


def test_a_provider_failure_while_deleting_keeps_the_connection_and_the_engine_restores_the_folder(
    monkeypatch: pytest.MonkeyPatch,
):
    with given(_GIVEN) as context:
        _synced_agents(context)
        revokes = _record_revokes(context, monkeypatch)
        plugin = fake_drive(context)
        delete = plugin.delete_item
        deletes: list[str] = []

        def delete_item(root, *, item_id: str) -> None:
            deletes.append(item_id)
            if len(deletes) == 2:
                raise ProviderUnavailable("Test Drive is down.")
            delete(root, item_id=item_id)

        monkeypatch.setattr(plugin, "delete_item", delete_item)

        with when("the provider fails on the second folder"):
            response = _disconnect(context)

        with then("the disconnect fails, nothing is revoked, and the connection stays active"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY), response.text)
            assert_that(revokes, equal_to([]))
            assert_that(_connection_status(context), equal_to(SyncProviderStatus.ACTIVE))
            assert_that(_folders(context), has_length(1))
            assert_that(_live_children(context), has_length(1))

        with then("the next engine pass gives the Agent whose folder was deleted a new one"):
            context.injector.get(FileSyncEngine).reconcile_folders(context.connection)
            assert_that(_folders(context), has_length(2))
            assert_that(_live_children(context), equal_to(["Sales Bot", "Support"]))


def test_a_failed_revoke_keeps_the_connection_and_the_engine_rebuilds_the_folders(monkeypatch: pytest.MonkeyPatch):
    with given(_GIVEN) as context:
        _synced_agents(context)
        plugin = fake_drive(context)

        def revoke(token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
            raise ProviderUnavailable("Test Drive is down.")

        monkeypatch.setattr(plugin, "revoke", revoke)

        response = _disconnect(context)

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY), response.text)
        assert_that(_connection_status(context), equal_to(SyncProviderStatus.ACTIVE))
        context.injector.get(FileSyncEngine).reconcile_folders(context.connection)
        assert_that(_live_children(context), equal_to(["Sales Bot", "Support"]))


def test_a_disconnect_that_cannot_get_the_connection_from_the_engine_changes_nothing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(file_sync_service, "DISCONNECT_LOCK_WAIT_SECONDS", 0.5)
    with given(_GIVEN) as context:
        _synced_agents(context)
        revokes = _record_revokes(context, monkeypatch)
        held, release = threading.Event(), threading.Event()

        def engine_pass() -> None:
            with context.injector.get(FileSyncRepository).connection_lock(context.connection.id) as acquired:
                assert acquired
                held.set()
                release.wait(10)

        engine = threading.Thread(target=engine_pass)
        engine.start()
        try:
            assert held.wait(10)
            response = _disconnect(context)
        finally:
            release.set()
            engine.join(10)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(response.json()["detail"], contains_string("busy"))
        assert_that((revokes, _live_children(context)), equal_to(([], ["Sales Bot", "Support"])))
        assert_that(_connection_status(context), equal_to(SyncProviderStatus.ACTIVE))


def test_a_disconnect_waits_for_a_running_engine_pass(monkeypatch: pytest.MonkeyPatch):
    with given(_GIVEN) as context:
        _synced_agents(context)
        _record_revokes(context, monkeypatch)
        plugin = fake_drive(context)
        delete = plugin.delete_item
        held = threading.Event()
        events: list[str] = []

        def delete_item(root, *, item_id: str) -> None:
            events.append("delete")
            delete(root, item_id=item_id)

        monkeypatch.setattr(plugin, "delete_item", delete_item)

        def engine_pass() -> None:
            with context.injector.get(FileSyncRepository).connection_lock(context.connection.id) as acquired:
                assert acquired
                held.set()
                time.sleep(1)
                events.append("engine done")

        engine = threading.Thread(target=engine_pass)
        engine.start()
        assert held.wait(10)
        response = _disconnect(context)
        engine.join(10)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(events, equal_to(["engine done", "delete", "delete"]))
        assert_that(_live_children(context), equal_to([]))
