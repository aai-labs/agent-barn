from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from hamcrest import assert_that, close_to, equal_to, none, not_none
from sqlmodel import Session

from api.domains.agents.models import Agent, AgentStatus
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import (
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
    SyncPendingAction,
)
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.plugins.base import ProviderThrottled, RemoteChanges, RemoteItemMissing, SyncRoot
from api.tests.core.givenpy import given
from api.tests.steps.file_sync_ingest import (
    AGENT_KEY,
    activity_entries,
    agent_folder,
    file_sync_ingest_base,
    ready_agent,
    synced_files,
    upload_through_the_pod,
)
from api.tests.steps.file_sync_provider import fake_drive

_BASE = file_sync_ingest_base(clean_database=True)


def _engine(context) -> FileSyncEngine:
    return context.injector.get(FileSyncEngine)


def _connection(context) -> SyncProviderConnection:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(SyncProviderConnection, context.connection.id)
        assert row is not None
        return row


def _process(context) -> None:
    _engine(context).process_changes(_connection(context))


def _connected_with(context, *files: tuple[str, bytes]) -> Agent:
    agent = ready_agent(context)
    _process(context)
    for path, content in files:
        upload_through_the_pod(context, agent, path, content)
    _process(context)
    return agent


def _exists(context, remote_path: str) -> bool:
    try:
        fake_drive(context).get_item_by_path(
            context.sync_root, parent_id=context.sync_root.folder_id, rel_path=remote_path
        )
    except RemoteItemMissing:
        return False
    return True


def _row(context, path: str) -> SyncFile:
    return synced_files(context)[path]


def _while_listing(context, monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> None:
    drive = fake_drive(context)
    listing = drive.changes
    acted: list[bool] = []

    def changes(root: SyncRoot, cursor: str | None, *, from_start: bool = False) -> RemoteChanges:
        page = listing(root, cursor, from_start=from_start)
        if from_start and not acted:
            acted.append(True)
            action()
        return page

    monkeypatch.setattr(drive, "changes", changes)


def _turn_sync(context, agent: Agent, *, on: bool) -> None:
    with Session(context.postgres_delegate.engine) as session:
        agent_row = session.get(Agent, agent.id)
        folder = session.get(SyncAgentFolder, agent_folder(context).id)
        assert agent_row is not None and folder is not None
        agent_row.file_sync_enabled = on
        folder.status = SyncFolderStatus.ACTIVE if on else SyncFolderStatus.DISABLED
        if on:
            folder.resync_requested_at = datetime.now(UTC)
        session.add(agent_row)
        session.add(folder)
        session.commit()


def _off_while(context, agent: Agent, people_change: Callable[[], None]) -> None:
    _turn_sync(context, agent, on=False)
    people_change()
    _process(context)


def _count_listings(context, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    drive = fake_drive(context)
    listing = drive.changes
    listings: list[bool] = []

    def changes(root: SyncRoot, cursor: str | None, *, from_start: bool = False) -> RemoteChanges:
        if from_start:
            listings.append(True)
        return listing(root, cursor, from_start=from_start)

    monkeypatch.setattr(drive, "changes", changes)
    return listings


def test_an_expired_cursor_relists_everything_without_inventing_edits():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"), ("workspace/AGENTS.md", b"rules"))
        old_cursor = _connection(context).sync_cursor
        fake_drive(context).expire_cursors()

        _process(context)

        assert_that(_connection(context).sync_cursor == old_cursor, equal_to(False))
        assert_that([row.pending for row in synced_files(context).values()], equal_to([None, None]))
        assert_that(activity_entries(context), equal_to([]))


def test_edits_made_while_the_cursor_was_expired_are_found_by_the_relisting():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"), ("workspace/AGENTS.md", b"rules"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"mine")
        fake_drive(context).expire_cursors()

        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))
        assert_that(_row(context, "workspace/AGENTS.md").pending, equal_to(SyncPendingAction.REUPLOAD))
        assert_that(
            (activity_entries(context), _row(context, "workspace/AGENTS.md").pending_activity),
            equal_to(([], SyncActivityKind.EDIT_UNDONE)),
        )


def test_files_deleted_while_the_cursor_was_expired_are_restored():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"), ("workspace/kept.md", b"k"))
        fake_drive(context).user_deletes(context.sync_root, "Sales Bot/workspace/notes.md")
        fake_drive(context).expire_cursors()

        _process(context)

        row = _row(context, "workspace/notes.md")
        assert_that((row.pending, row.item_id), equal_to((SyncPendingAction.REUPLOAD, None)))
        assert_that(_row(context, "workspace/kept.md").pending, none())
        assert_that(
            (activity_entries(context), _row(context, "workspace/notes.md").pending_activity),
            equal_to(([], SyncActivityKind.RESTORED)),
        )


def test_files_added_while_the_cursor_was_expired_are_parked():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/mine.md", b"mine")
        fake_drive(context).expire_cursors()

        _process(context)

        assert_that(_exists(context, "Sales Bot/_Not synced/mine.md"), equal_to(True))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.MOVED_NOT_SYNCED, "workspace/mine.md")]))


def test_an_agent_folder_deleted_while_the_cursor_was_expired_is_rebuilt():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_deletes(context.sync_root, "Sales Bot")
        fake_drive(context).expire_cursors()

        _process(context)

        assert_that(agent_folder(context).folder_item_id, none())
        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.REUPLOAD))
        assert_that((SyncActivityKind.FOLDER_RESTORED, None) in activity_entries(context), equal_to(True))


def test_after_a_relisting_the_feed_continues_from_the_fresh_cursor():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).expire_cursors()
        _process(context)

        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"later")
        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))


def test_a_relisting_spanning_several_pages_saves_its_cursor_only_at_the_end():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/a.md", b"a"), ("workspace/b.md", b"b"), ("workspace/c.md", b"c"))
        fake_drive(context).page_size = 2
        fake_drive(context).user_deletes(context.sync_root, "Sales Bot/workspace/c.md")
        fake_drive(context).expire_cursors()

        _process(context)

        assert_that(_row(context, "workspace/c.md").pending, equal_to(SyncPendingAction.REUPLOAD))
        assert_that(
            [_row(context, path).pending for path in ("workspace/a.md", "workspace/b.md")], equal_to([None, None])
        )


def test_throttling_while_reading_changes_keeps_the_cursor_and_pauses_only_that_connection():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        cursor = _connection(context).sync_cursor
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")
        fake_drive(context).throttle_call("changes", 120)
        now = datetime.now(UTC)

        _engine(context).run_pass(now)

        connection = _connection(context)
        assert connection.sync_retry_at is not None
        assert_that((connection.sync_retry_at - now).total_seconds(), close_to(120, 1))
        assert_that(connection.sync_cursor, equal_to(cursor))
        assert_that(_row(context, "workspace/notes.md").pending, none())

        _engine(context).run_pass(now + timedelta(seconds=121))

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))


def test_a_page_interrupted_by_throttling_is_read_again_without_doing_anything_twice():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        cursor = _connection(context).sync_cursor
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/first.md", b"1")
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/second.md", b"2")
        fake_drive(context).user_renames(context.sync_root, "Sales Bot/workspace/notes.md", "renamed.md")
        moves_before = fake_drive(context).calls.count("move_item")
        fake_drive(context).throttle_call("get_item_by_path", 30)

        with pytest.raises(ProviderThrottled):
            _process(context)
        interrupted_cursor = _connection(context).sync_cursor
        _process(context)

        assert_that(interrupted_cursor, equal_to(cursor))
        assert_that(_exists(context, "Sales Bot/_Not synced/first.md"), equal_to(True))
        assert_that(_exists(context, "Sales Bot/_Not synced/second.md"), equal_to(True))
        assert_that(_exists(context, "Sales Bot/workspace/notes.md"), equal_to(True))
        assert_that(
            sorted(activity_entries(context), key=str),
            equal_to(
                sorted(
                    [
                        (SyncActivityKind.MOVED_NOT_SYNCED, "workspace/first.md"),
                        (SyncActivityKind.MOVED_NOT_SYNCED, "workspace/second.md"),
                        (SyncActivityKind.RENAMED_BACK, "workspace/notes.md"),
                    ],
                    key=str,
                )
            ),
        )
        assert_that(fake_drive(context).calls.count("move_item") - moves_before, equal_to(3))


def test_a_stopped_agents_jobs_wait_for_its_pod():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(Agent, agent.id)
            assert row is not None
            row.status = AgentStatus.STOPPED
            session.add(row)
            session.commit()
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)
        _process(context)
        with Session(context.postgres_delegate.engine) as session:
            job = session.get(SyncFile, _row(context, "workspace/notes.md").id)
            assert job is not None
            job.retry_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(job)
            session.commit()
        operations = context.ingest_client.get(
            f"/ingest/v1/agents/{agent.id}/file-sync/operations", headers={"Authorization": f"Bearer {AGENT_KEY}"}
        ).json()["operations"]

        assert_that([(op["path"], op["action"]) for op in operations], equal_to([("workspace/notes.md", "download")]))
        assert_that(_row(context, "workspace/notes.md").lease_until, not_none())


def test_a_file_the_pod_uploads_during_a_relisting_is_not_restored(monkeypatch):
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).expire_cursors()
        _while_listing(
            context, monkeypatch, lambda: upload_through_the_pod(context, agent, "workspace/report.md", b"fresh")
        )

        _process(context)

        assert_that(_row(context, "workspace/report.md").pending, none())
        assert_that(activity_entries(context), equal_to([]))


def test_a_file_deleted_during_a_relisting_does_not_fail_the_pass(monkeypatch):
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/budget.xlsx", b"numbers")
        fake_drive(context).expire_cursors()
        _while_listing(
            context,
            monkeypatch,
            lambda: fake_drive(context).user_deletes(context.sync_root, "Sales Bot/workspace/budget.xlsx"),
        )

        failure: Exception | None = None
        try:
            _process(context)
        except Exception as exc:
            failure = exc

        assert_that(failure, none())
        assert_that(activity_entries(context), equal_to([]))


def test_edits_made_while_sync_was_off_are_found_when_it_is_turned_on():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"), ("workspace/AGENTS.md", b"rules"))

        def people_edit() -> None:
            fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")
            fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"mine")

        _off_while(context, agent, people_edit)

        assert_that([row.pending for row in synced_files(context).values()], equal_to([None, None]))

        _turn_sync(context, agent, on=True)
        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))
        assert_that(
            (_row(context, "workspace/AGENTS.md").pending, _row(context, "workspace/AGENTS.md").pending_activity),
            equal_to((SyncPendingAction.REUPLOAD, SyncActivityKind.EDIT_UNDONE)),
        )


def test_deletes_and_new_files_made_while_sync_was_off_are_handled_when_it_is_turned_on():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))

        def people_change() -> None:
            fake_drive(context).user_deletes(context.sync_root, "Sales Bot/workspace/notes.md")
            fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/mine.md", b"mine")

        _off_while(context, agent, people_change)
        _turn_sync(context, agent, on=True)

        _process(context)

        row = _row(context, "workspace/notes.md")
        assert_that(
            (row.pending, row.pending_activity), equal_to((SyncPendingAction.REUPLOAD, SyncActivityKind.RESTORED))
        )
        assert_that(_exists(context, "Sales Bot/_Not synced/mine.md"), equal_to(True))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.MOVED_NOT_SYNCED, "workspace/mine.md")]))


def test_a_folder_deleted_while_sync_was_off_is_rebuilt_when_it_is_turned_on():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        _off_while(context, agent, lambda: fake_drive(context).user_deletes(context.sync_root, "Sales Bot"))
        _turn_sync(context, agent, on=True)

        _process(context)

        assert_that(agent_folder(context).folder_item_id, none())
        assert_that((SyncActivityKind.FOLDER_RESTORED, None) in activity_entries(context), equal_to(True))


def test_the_re_check_request_is_cleared_after_the_pass():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        _off_while(context, agent, lambda: None)
        _turn_sync(context, agent, on=True)

        _process(context)

        assert_that(agent_folder(context).resync_requested_at, none())


def test_a_turn_on_made_during_a_re_check_survives_it(monkeypatch):
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        _off_while(context, agent, lambda: None)
        _turn_sync(context, agent, on=True)
        _while_listing(context, monkeypatch, lambda: _turn_sync(context, agent, on=True))

        _process(context)

        assert_that(agent_folder(context).resync_requested_at, not_none())


def test_two_turn_ons_before_a_pass_cause_one_re_check(monkeypatch):
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        _off_while(context, agent, lambda: None)
        _turn_sync(context, agent, on=True)
        _turn_sync(context, agent, on=False)
        _turn_sync(context, agent, on=True)
        listings = _count_listings(context, monkeypatch)

        _process(context)
        _process(context)

        assert_that(len(listings), equal_to(1))
