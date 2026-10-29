from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, close_to, equal_to, none, not_none
from sqlmodel import Session, select

from api.domains.agents.models import Agent
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import (
    SyncActivity,
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
    SyncPendingAction,
)
from api.domains.sync_provider.models import SyncProviderConnection
from api.tests.core.givenpy import given
from api.tests.steps.file_sync_ingest import (
    AGENT_KEY,
    activity_entries,
    agent_folder,
    complete_upload,
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


def _row(context, path: str) -> SyncFile:
    return synced_files(context)[path]


def _claim(context, agent: Agent):
    return context.ingest_client.get(
        f"/ingest/v1/agents/{agent.id}/file-sync/operations", headers={"Authorization": f"Bearer {AGENT_KEY}"}
    ).json()["operations"]


def _settle(context, path: str) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(SyncFile, _row(context, path).id)
        assert row is not None
        row.retry_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(row)
        session.commit()


def test_the_first_pass_starts_the_change_feed_from_now():
    with given(_BASE) as context:
        ready_agent(context)
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/before.md", b"x")

        _process(context)

        assert_that(_connection(context).sync_cursor, not_none())
        assert_that((synced_files(context), activity_entries(context)), equal_to(({}, [])))


def test_the_agents_own_uploads_in_the_feed_change_nothing():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))

        row = _row(context, "workspace/notes.md")
        assert_that((row.pending, row.retry_at), equal_to((None, None)))
        assert_that(activity_entries(context), equal_to([]))


def test_a_persons_edit_to_a_work_file_becomes_a_download_after_the_autosave_wait():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)
        while_settling = _claim(context, agent)
        _settle(context, "workspace/notes.md")
        settled = _claim(context, agent)

        row = _row(context, "workspace/notes.md")
        assert_that(row.pending, equal_to(SyncPendingAction.DOWNLOAD))
        assert_that(while_settling, equal_to([]))
        assert_that([(op["path"], op["action"]) for op in settled], equal_to([("workspace/notes.md", "download")]))


def test_the_download_waits_thirty_seconds_after_the_last_edit():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)

        retry_at = _row(context, "workspace/notes.md").retry_at
        assert retry_at is not None
        assert_that((retry_at - datetime.now(UTC)).total_seconds(), close_to(30, 5))


def test_a_persons_edit_to_a_memory_file_becomes_a_download():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/USER.md", b"profile"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/USER.md", b"edited profile")

        _process(context)

        assert_that(_row(context, "workspace/USER.md").pending, equal_to(SyncPendingAction.DOWNLOAD))


def test_a_persons_edit_to_a_config_file_is_queued_with_its_note_owed():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/AGENTS.md", b"rules"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"my rules")

        _process(context)
        _settle(context, "workspace/AGENTS.md")
        operations = _claim(context, agent)

        assert_that(_row(context, "workspace/AGENTS.md").pending, equal_to(SyncPendingAction.REUPLOAD))
        assert_that([(op["path"], op["action"]) for op in operations], equal_to([("workspace/AGENTS.md", "reupload")]))
        assert_that(
            (activity_entries(context), _row(context, "workspace/AGENTS.md").pending_activity),
            equal_to(([], SyncActivityKind.EDIT_UNDONE)),
        )


def test_a_persons_edit_to_a_skill_file_is_queued_with_its_note_owed():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/skills/jira/SKILL.md", b"skill"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/skills/jira/SKILL.md", b"changed")

        _process(context)

        assert_that(_row(context, "workspace/skills/jira/SKILL.md").pending, equal_to(SyncPendingAction.REUPLOAD))
        assert_that(
            (activity_entries(context), _row(context, "workspace/skills/jira/SKILL.md").pending_activity),
            equal_to(([], SyncActivityKind.EDIT_UNDONE)),
        )


def test_repeated_edits_keep_one_download_and_push_its_wait_back():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"one")
        _process(context)
        _settle(context, "workspace/notes.md")

        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"two")
        _process(context)

        row = _row(context, "workspace/notes.md")
        assert row.retry_at is not None
        assert_that((row.pending, row.retry_at > datetime.now(UTC)), equal_to((SyncPendingAction.DOWNLOAD, True)))


def test_a_pending_undo_is_not_replaced_by_a_later_edit():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/AGENTS.md", b"rules"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"one")
        _process(context)

        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"two")
        _process(context)

        row = _row(context, "workspace/AGENTS.md")
        assert_that(
            (row.pending, row.pending_activity), equal_to((SyncPendingAction.REUPLOAD, SyncActivityKind.EDIT_UNDONE))
        )
        assert_that(activity_entries(context), equal_to([]))


def test_a_change_while_the_agents_upload_is_under_way_is_left_to_the_upload_and_recorded_as_a_conflict():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        context.ingest_client.post(
            f"/ingest/v1/agents/{agent.id}/file-sync/changes",
            json={"complete": True, "entries": [{"path": "workspace/notes.md", "size": 9, "sha256": "b" * 64}]},
            headers={"Authorization": f"Bearer {AGENT_KEY}"},
        )
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, none())
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.CONFLICT_AGENT_WON, "workspace/notes.md")]))


def test_a_persons_edit_over_the_size_limit_is_skipped_and_recorded():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_edits(
            context.sync_root, "Sales Bot/workspace/notes.md", b"x" * (100 * 1024 * 1024 + 1)
        )

        _process(context)
        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, none())
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_TOO_LARGE, "workspace/notes.md")]))


def test_edits_in_a_folder_with_sync_off_are_ignored():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        with Session(context.postgres_delegate.engine) as session:
            folder = session.get(SyncAgentFolder, agent_folder(context).id)
            assert folder is not None
            folder.status = SyncFolderStatus.DISABLED
            session.add(folder)
            session.commit()
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, none())


def test_a_persons_edit_after_the_agents_sync_is_turned_off_is_left_alone():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/notes.md", b"hello"))
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(Agent, agent.id)
            assert row is not None
            row.file_sync_enabled = False
            session.add(row)
            session.commit()
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _engine(context).run_pass(datetime.now(UTC))

        assert_that(agent_folder(context).status, equal_to(SyncFolderStatus.DISABLED))
        assert_that(_row(context, "workspace/notes.md").pending, none())
        assert_that(activity_entries(context), equal_to([]))


def test_the_cursor_moves_on_so_an_edit_is_handled_once():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/AGENTS.md", b"rules"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"mine")
        _process(context)
        before = _connection(context).sync_cursor
        retry_at = _row(context, "workspace/AGENTS.md").retry_at

        _process(context)

        assert_that(_connection(context).sync_cursor == before, equal_to(True))
        assert_that(_row(context, "workspace/AGENTS.md").retry_at, equal_to(retry_at))


def test_a_full_engine_pass_reads_the_change_feed():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _engine(context).run_pass(datetime.now(UTC))

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))


def test_the_undo_note_is_written_when_the_agents_copy_is_back():
    with given(_BASE) as context:
        agent = _connected_with(context, ("workspace/AGENTS.md", b"rules"))
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/AGENTS.md", b"my rules")
        _process(context)
        _settle(context, "workspace/AGENTS.md")
        operation = _claim(context, agent)[0]
        before = datetime.now(UTC)

        fake_drive(context).complete_upload(operation["url"], b"rules")
        response = complete_upload(context, agent, "workspace/AGENTS.md")

        assert_that(response.status_code, equal_to(204))
        with Session(context.postgres_delegate.engine) as session:
            notes = list(session.exec(select(SyncActivity)))
        assert_that([(note.kind, note.path) for note in notes], equal_to([("edit_undone", "workspace/AGENTS.md")]))
        assert_that(notes[0].occurred_at >= before, equal_to(True))
        assert_that(_row(context, "workspace/AGENTS.md").pending_activity, none())


def test_an_edit_reported_without_a_path_is_still_found():
    with given(_BASE) as context:
        _connected_with(context, ("workspace/notes.md", b"hello"))
        fake_drive(context).omit_paths_in_changes = True
        fake_drive(context).user_edits(context.sync_root, "Sales Bot/workspace/notes.md", b"edited")

        _process(context)

        assert_that(_row(context, "workspace/notes.md").pending, equal_to(SyncPendingAction.DOWNLOAD))
