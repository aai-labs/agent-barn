from datetime import UTC, datetime, timedelta

import pytest
from hamcrest import assert_that, equal_to, none, not_none
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.file_sync.models import (
    SyncActivity,
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
    SyncPendingAction,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.repository import SyncProviderRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

_GIVEN = [prepare_injector(), database_repo_is_ready(), there_is_an_organization(), there_is_an_agent()]


def _active_connection(context) -> SyncProviderConnection:
    repository = context.injector.get(SyncProviderRepository)
    pending = repository.create_pending(
        context.organization.id,
        "onedrive",
        schema_version=1,
        account_id="tenant-1",
        connected_by_user_id=context.user.id,
        credentials_encrypted="encrypted-token",
        pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    active = repository.activate(
        pending.id,
        location_id="site-1",
        location_name="Agent Barn Test",
        location_url="https://contoso.sharepoint.com/sites/AgentBarnTest",
        folder_id="barn-1",
        folder_web_url="https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn",
        provider_data={},
    )
    assert active is not None
    return active


def _save(context, *rows):
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        for row in rows:
            session.add(row)
        session.commit()
    return rows[0] if len(rows) == 1 else rows


def _folder(context, connection, agent_id=None, name="Test Agent") -> SyncAgentFolder:
    return SyncAgentFolder(
        organization_id=context.organization.id,
        connection_id=connection.id,
        agent_id=agent_id or context.agent.id,
        folder_name=name,
        status=SyncFolderStatus.ACTIVE,
    )


def _synced(folder, path="workspace/notes.md", item_id="item-1") -> SyncFile:
    return SyncFile(
        folder_id=folder.id,
        path=path,
        item_id=item_id,
        etag='"{A},1"',
        ctag='"c:{A},1"',
        remote_hash="aSZzG9jwBhDYIQYgIYMc3tAGEIQ=",
        local_sha256="0" * 64,
        size=17,
        synced_at=datetime.now(UTC),
    )


def _uploading(folder, path) -> SyncFile:
    return SyncFile(folder_id=folder.id, path=path, local_sha256="0" * 64, size=17, upload_started_at=datetime.now(UTC))


def _activity(context, folder, kind=SyncActivityKind.EDIT_UNDONE) -> SyncActivity:
    return SyncActivity(
        organization_id=context.organization.id,
        agent_id=context.agent.id,
        folder_id=folder.id,
        kind=kind,
        path="workspace/SOUL.md",
        occurred_at=datetime.now(UTC),
    )


def _get(context, model, row_id):
    with Session(context.postgres_delegate.engine) as session:
        return session.get(model, row_id)


def test_a_folder_is_stored_with_its_defaults():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))

        found = _get(context, SyncAgentFolder, folder.id)

        assert found is not None
        assert_that(found.status, equal_to(SyncFolderStatus.ACTIVE))
        assert_that(found.folder_item_id, none())
        assert_that(found.last_contact_at, none())


def test_an_agent_has_one_folder_per_connection():
    with given(_GIVEN) as context:
        connection = _active_connection(context)
        _save(context, _folder(context, connection, name="First"))

        with pytest.raises(IntegrityError):
            _save(context, _folder(context, connection, name="Second"))


def test_two_folders_on_one_connection_cannot_share_a_name_in_any_case():
    with given(_GIVEN) as context:
        connection = _active_connection(context)
        first_agent = context.agent.id
        there_is_an_agent(name="Other Agent")(context)
        _save(context, _folder(context, connection, agent_id=first_agent, name="Sales Bot"))

        with pytest.raises(IntegrityError):
            _save(context, _folder(context, connection, agent_id=context.agent.id, name="sales bot"))


def test_a_file_path_is_unique_per_folder_in_any_case():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))
        _save(context, _synced(folder, path="workspace/Notes.md", item_id="item-1"))

        with pytest.raises(IntegrityError):
            _save(context, _uploading(folder, path="workspace/notes.md"))


def test_a_provider_item_is_recorded_once_per_folder():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))
        _save(context, _synced(folder, path="workspace/a.md", item_id="item-1"))

        with pytest.raises(IntegrityError):
            _save(context, _synced(folder, path="workspace/b.md", item_id="item-1"))


def test_several_first_uploads_can_be_under_way_without_a_provider_item():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))

        first, second = _save(context, _uploading(folder, "workspace/a.md"), _uploading(folder, "workspace/b.md"))

        found = _get(context, SyncFile, first.id)
        assert found is not None
        assert_that(found.item_id, none())
        assert_that(found.synced_at, none())
        assert_that(found.upload_started_at, not_none())
        assert_that(_get(context, SyncFile, second.id), not_none())


def test_a_file_starts_with_no_pending_work():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))

        found = _get(context, SyncFile, _save(context, _synced(folder)).id)

        assert found is not None
        assert_that(found.pending, none())
        assert_that(found.attempts, equal_to(0))
        assert_that(found.lease_until, none())
        assert_that(found.retry_at, none())


def test_pending_work_is_stored_on_the_file():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))
        row = _synced(folder)
        row.pending = SyncPendingAction.REUPLOAD

        found = _get(context, SyncFile, _save(context, row).id)

        assert found is not None
        assert_that(found.pending, equal_to(SyncPendingAction.REUPLOAD))


def test_the_connection_keeps_its_change_cursor_and_retry_time():
    with given(_GIVEN) as context:
        connection = _active_connection(context)
        assert_that(connection.sync_cursor, none())
        cursor = "https://graph.microsoft.com/v1.0/drives/b!x/items/y/delta?token=z"
        retry_at = datetime.now(UTC) + timedelta(seconds=120)

        with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
            row = session.get(SyncProviderConnection, connection.id)
            assert row is not None
            row.sync_cursor = cursor
            row.sync_retry_at = retry_at
            session.add(row)
            session.commit()

        found = _get(context, SyncProviderConnection, connection.id)
        assert found is not None
        assert_that(found.sync_cursor, equal_to(cursor))
        assert_that(found.sync_retry_at, equal_to(retry_at))


def test_removing_a_folder_removes_its_files_and_keeps_its_activity():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))
        _save(context, _synced(folder))
        activity = _save(context, _activity(context, folder))

        with Session(context.postgres_delegate.engine) as session:
            session.delete(session.get(SyncAgentFolder, folder.id))
            session.commit()

        kept = _get(context, SyncActivity, activity.id)
        assert kept is not None
        assert_that(kept.folder_id, none())
        assert_that(kept.kind, equal_to(SyncActivityKind.EDIT_UNDONE))
        with Session(context.postgres_delegate.engine) as session:
            files = session.exec(select(SyncFile).where(col(SyncFile.folder_id) == folder.id)).all()
        assert_that(files, equal_to([]))


def test_deleting_the_organization_deletes_its_folders_and_activity():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))
        activity = _save(context, _activity(context, folder, kind=SyncActivityKind.SKIPPED_TOO_LARGE))

        context.injector.get(OrganizationRepository).delete(context.organization.id)

        assert_that(_get(context, SyncAgentFolder, folder.id), none())
        assert_that(_get(context, SyncActivity, activity.id), none())


def test_a_soft_deleted_agent_keeps_its_folder():
    with given(_GIVEN) as context:
        folder = _save(context, _folder(context, _active_connection(context)))

        with Session(context.postgres_delegate.engine) as session:
            agent = session.get(Agent, context.agent.id)
            assert agent is not None
            agent.deleted_at = datetime.now(UTC)
            session.add(agent)
            session.commit()

        assert_that(_get(context, SyncAgentFolder, folder.id), not_none())
