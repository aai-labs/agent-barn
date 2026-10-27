from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, close_to, contains_inanyorder, equal_to, none
from sqlmodel import Session, col, select

from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncAgentFolder
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.repository import SyncProviderRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.file_sync_provider import TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization

_BASE = [prepare_injector(modules=[TestDriveModule()]), database_repo_is_ready(), database_is_clean()]


def _connected_organization(context, name: str, agent_name: str) -> SyncProviderConnection:
    there_is_an_organization(name=name)(context)
    there_is_an_agent(name=agent_name)(context)
    there_is_a_sync_connection()(context)
    return context.connection


def _folder_names(context, connection: SyncProviderConnection) -> list[str]:
    with Session(context.postgres_delegate.engine) as session:
        return list(
            session.exec(select(SyncAgentFolder.folder_name).where(col(SyncAgentFolder.connection_id) == connection.id))
        )


def _connection(context, connection: SyncProviderConnection) -> SyncProviderConnection:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(SyncProviderConnection, connection.id)
        assert row is not None
        return row


def _retry_at(context, connection: SyncProviderConnection, retry_at: datetime | None) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(SyncProviderConnection, connection.id)
        assert row is not None
        row.sync_retry_at = retry_at
        session.add(row)
        session.commit()


def _run_pass(context, now: datetime | None = None) -> None:
    context.injector.get(FileSyncEngine).run_pass(now or datetime.now(UTC))


def test_a_pass_reconciles_every_active_connection():
    with given(_BASE) as context:
        first = _connected_organization(context, "First", "Sales Bot")
        second = _connected_organization(context, "Second", "Support")

        _run_pass(context)

        assert_that(_folder_names(context, first), equal_to(["Sales Bot"]))
        assert_that(_folder_names(context, second), equal_to(["Support"]))


def test_a_connection_waiting_out_throttling_is_skipped_until_its_time():
    with given(_BASE) as context:
        connection = _connected_organization(context, "First", "Sales Bot")
        now = datetime.now(UTC)
        _retry_at(context, connection, now + timedelta(seconds=60))

        _run_pass(context, now)
        skipped = _folder_names(context, connection)
        _run_pass(context, now + timedelta(seconds=61))

        assert_that((skipped, _folder_names(context, connection)), equal_to(([], ["Sales Bot"])))


def test_throttling_postpones_only_that_connection_by_the_providers_wait():
    with given(_BASE) as context:
        throttled = _connected_organization(context, "First", "Sales Bot")
        other = _connected_organization(context, "Second", "Support")
        now = datetime.now(UTC)
        fake_drive(context).throttle_next(120)

        _run_pass(context, now)

        retry_at = _connection(context, throttled).sync_retry_at or _connection(context, other).sync_retry_at
        assert retry_at is not None
        assert_that((retry_at - now).total_seconds(), close_to(120, 1))
        assert_that(
            [_folder_names(context, throttled), _folder_names(context, other)],
            contains_inanyorder(["Sales Bot"], ["Support"]),
        )


def test_a_failing_connection_does_not_stop_the_others():
    with given(_BASE) as context:
        healthy = _connected_organization(context, "First", "Sales Bot")
        there_is_an_organization(name="Second")(context)
        repository = context.injector.get(SyncProviderRepository)
        pending = repository.create_pending(
            context.organization.id,
            "removeddrive",
            schema_version=1,
            account_id="gone",
            connected_by_user_id=context.user.id,
            credentials_encrypted="x",
            pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        repository.activate(
            pending.id,
            location_id=None,
            location_name=None,
            location_url=None,
            folder_id="gone-root",
            folder_web_url="https://gone.example.test",
            provider_data={},
        )

        _run_pass(context)

        assert_that(_folder_names(context, healthy), equal_to(["Sales Bot"]))


def test_a_connection_another_engine_holds_is_skipped():
    with given(_BASE) as context:
        connection = _connected_organization(context, "First", "Sales Bot")

        with context.injector.get(FileSyncRepository).connection_lock(connection.id) as acquired:
            assert_that(acquired, equal_to(True))
            _run_pass(context)
            held = _folder_names(context, connection)
        _run_pass(context)

        assert_that((held, _folder_names(context, connection)), equal_to(([], ["Sales Bot"])))


def test_pending_and_disconnected_connections_are_not_synced():
    with given(_BASE) as context:
        connection = _connected_organization(context, "First", "Sales Bot")
        context.injector.get(SyncProviderRepository).mark_disconnected(connection.id)

        _run_pass(context)

        assert_that(_folder_names(context, connection), equal_to([]))
        assert_that(_connection(context, connection).sync_retry_at, none())


def test_a_pass_reports_progress_for_each_connection_and_each_page_of_changes():
    with given(_BASE) as context:
        _connected_organization(context, "Acme", "Sales Bot")
        _run_pass(context)
        plugin = fake_drive(context)
        plugin.page_size = 1
        for name in ("a.md", "b.md", "c.md"):
            plugin.user_adds(context.sync_root, f"Sales Bot/workspace/{name}", b"x")
        ticks: list[int] = []

        context.injector.get(FileSyncEngine).run_pass(datetime.now(UTC), progress=lambda: ticks.append(1))

        assert_that(len(ticks) >= 4, equal_to(True))
