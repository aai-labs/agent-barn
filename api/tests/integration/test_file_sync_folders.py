from datetime import UTC, datetime

import pytest
from hamcrest import assert_that, contains_inanyorder, equal_to, has_length, not_none
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import (
    SyncActivity,
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
)
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.plugins.base import ProviderThrottled, ProviderUnavailable
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.file_sync_ingest import SHA_A
from api.tests.steps.file_sync_provider import TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.sync_provider import OTHER_DRIVE

_BASE = [prepare_injector(modules=[TestDriveModule()]), database_repo_is_ready(), there_is_an_organization()]


def _reconcile(context) -> None:
    context.injector.get(FileSyncEngine).reconcile_folders(context.connection)


def _agent(context, name: str) -> Agent:
    there_is_an_agent(name=name)(context)
    return context.agent


def _folders(context) -> list[SyncAgentFolder]:
    with Session(context.postgres_delegate.engine) as session:
        return list(
            session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.connection_id) == context.connection.id))
        )


def _folder(context, agent: Agent) -> SyncAgentFolder:
    return next(folder for folder in _folders(context) if folder.agent_id == agent.id)


def _provider_folders(context) -> list[str]:
    plugin = fake_drive(context)
    root_id = context.sync_root.folder_id
    return [node.name for node in plugin.nodes.values() if node.parent_id == root_id and not node.deleted]


def _update_agent(context, agent: Agent, **fields) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(Agent, agent.id)
        assert row is not None
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()


def test_connecting_gives_every_existing_agent_a_folder_named_after_it():
    with given(_BASE) as context:
        sales, support = _agent(context, "Sales Bot"), _agent(context, "Support")
        there_is_a_sync_connection()(context)

        _reconcile(context)

        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Support"))
        for agent, name in ((sales, "Sales Bot"), (support, "Support")):
            folder = _folder(context, agent)
            assert_that((folder.folder_name, folder.status), equal_to((name, SyncFolderStatus.ACTIVE)))
            assert_that(folder.folder_item_id, not_none())
            assert_that(folder.folder_web_url, not_none())
            assert_that(folder.folder_path, not_none())
            assert_that(folder.organization_id, equal_to(context.organization.id))


def test_an_agent_created_later_gets_a_folder_on_the_next_pass_and_nothing_else_is_touched():
    with given(_BASE) as context:
        _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        calls_before = len(fake_drive(context).calls)

        _agent(context, "Support")
        _reconcile(context)

        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Support"))
        assert_that(fake_drive(context).calls[calls_before:], equal_to(["create_folder"]))


def test_a_pass_with_nothing_to_do_calls_the_provider_not_at_all():
    with given(_BASE) as context:
        _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        calls_before = len(fake_drive(context).calls)

        _reconcile(context)

        assert_that(fake_drive(context).calls[calls_before:], equal_to([]))


def test_duplicate_names_get_a_number():
    with given(_BASE) as context:
        agents = [_agent(context, "Sales Bot") for _ in range(3)]
        there_is_a_sync_connection()(context)

        _reconcile(context)

        assert_that(
            sorted(_folder(context, agent).folder_name for agent in agents),
            equal_to(["Sales Bot", "Sales Bot (2)", "Sales Bot (3)"]),
        )
        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Sales Bot (2)", "Sales Bot (3)"))


def test_names_differing_only_in_case_are_duplicates():
    with given(_BASE) as context:
        first, second = _agent(context, "Sales Bot"), _agent(context, "sales bot")
        there_is_a_sync_connection()(context)

        _reconcile(context)

        assert_that(
            sorted((_folder(context, first).folder_name, _folder(context, second).folder_name)),
            equal_to(["Sales Bot", "sales bot (2)"]),
        )


@pytest.mark.parametrize(
    ("agent_name", "folder_name"),
    [
        ("Sales: EU", "Sales- EU"),
        ('A"B*C<D>E?F|G\\H/I', "A-B-C-D-E-F-G-H-I"),
        ("  Padded  ", "Padded"),
        ("Ends with dots...", "Ends with dots"),
        ("Q3 #1 50%", "Q3 #1 50%"),
        ("CON", "Agent"),
        ("_vti_bot", "Agent"),
        ("...", "Agent"),
    ],
)
def test_folder_names_follow_the_providers_naming_rules(agent_name, folder_name):
    with given(_BASE) as context:
        agent = _agent(context, agent_name)
        there_is_a_sync_connection()(context)

        _reconcile(context)

        assert_that(_folder(context, agent).folder_name, equal_to(folder_name))
        assert_that(_provider_folders(context), equal_to([folder_name]))


def test_a_long_name_is_cut_so_its_number_still_fits():
    with given(_BASE) as context:
        long_name = "n" * 255
        first, second = _agent(context, long_name), _agent(context, long_name)
        there_is_a_sync_connection()(context)

        _reconcile(context)

        names = sorted((_folder(context, first).folder_name, _folder(context, second).folder_name), key=len)
        assert_that(names[0], equal_to(long_name))
        assert_that(names[1], equal_to("n" * 251 + " (2)"))


def test_renaming_an_agent_renames_its_folder():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        item_id = _folder(context, agent).folder_item_id

        _update_agent(context, agent, name="Sales Team")
        _reconcile(context)

        folder = _folder(context, agent)
        assert_that((folder.folder_name, folder.folder_item_id), equal_to(("Sales Team", item_id)))
        assert_that(_provider_folders(context), equal_to(["Sales Team"]))


def test_two_agents_swapping_names_settle_without_ever_sharing_one():
    with given(_BASE) as context:
        first, second = _agent(context, "Alpha"), _agent(context, "Beta")
        there_is_a_sync_connection()(context)
        _reconcile(context)

        _update_agent(context, first, name="Beta")
        _update_agent(context, second, name="Alpha")
        _reconcile(context)
        _reconcile(context)

        assert_that(
            (_folder(context, first).folder_name, _folder(context, second).folder_name), equal_to(("Beta", "Alpha"))
        )
        assert_that(_provider_folders(context), contains_inanyorder("Alpha", "Beta"))


def test_a_numbered_name_drops_its_number_once_the_plain_name_is_free():
    with given(_BASE) as context:
        first, second = _agent(context, "Sales Bot"), _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        numbered = first if _folder(context, first).folder_name == "Sales Bot (2)" else second
        plain = second if numbered is first else first

        _update_agent(context, plain, name="Support")
        _reconcile(context)
        _reconcile(context)

        assert_that(_folder(context, numbered).folder_name, equal_to("Sales Bot"))
        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Support"))


def test_retiring_an_agent_deletes_its_folder_at_the_provider_and_keeps_its_activity():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        folder = _folder(context, agent)
        repository = context.injector.get(FileSyncRepository)
        repository.start_upload(folder.id, "workspace/notes.md", sha256=SHA_A, size=5, now=datetime.now(UTC))
        repository.record_activity(folder, SyncActivityKind.RESTORED, "workspace/notes.md", datetime.now(UTC))
        calls_before = len(fake_drive(context).calls)

        _update_agent(context, agent, deleted_at=datetime.now(UTC))
        _reconcile(context)

        assert_that(_provider_folders(context), equal_to([]))
        assert_that(fake_drive(context).calls[calls_before:], equal_to(["delete_item"]))
        assert_that(_folders(context), equal_to([]))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(list(session.exec(select(SyncFile))), equal_to([]))
            activity = list(session.exec(select(SyncActivity)))
        assert_that([(entry.kind, entry.folder_id) for entry in activity], equal_to([("restored", None)]))


def test_stopping_an_agent_keeps_its_folder_active():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        calls_before = len(fake_drive(context).calls)

        _update_agent(context, agent, status=AgentStatus.STOPPED)
        _reconcile(context)

        assert_that(_folder(context, agent).status, equal_to(SyncFolderStatus.ACTIVE))
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))
        assert_that(fake_drive(context).calls[calls_before:], equal_to([]))


def test_a_new_agent_named_like_a_retired_one_gets_the_plain_name_once_the_old_folder_is_gone():
    with given(_BASE) as context:
        old = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        _update_agent(context, old, deleted_at=datetime.now(UTC))

        new = _agent(context, "Sales Bot")
        _reconcile(context)

        assert_that(_folder(context, new).folder_name, equal_to("Sales Bot"))
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))


def test_a_retired_agents_folder_already_gone_at_the_provider_still_loses_its_row():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        fake_drive(context).user_deletes(context.sync_root, "Sales Bot")

        _update_agent(context, agent, deleted_at=datetime.now(UTC))
        _reconcile(context)

        assert_that(_folders(context), equal_to([]))


def test_a_throttled_folder_delete_waits_for_the_next_pass():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        _update_agent(context, agent, deleted_at=datetime.now(UTC))
        fake_drive(context).throttle_call("delete_item", 120)

        context.injector.get(FileSyncEngine).run_pass(datetime.now(UTC))

        assert_that(_folder(context, agent).status, equal_to(SyncFolderStatus.RETIRED))
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))
        with Session(context.postgres_delegate.engine) as session:
            connection = session.get(SyncProviderConnection, context.connection.id)
            assert connection is not None
            assert_that(connection.sync_retry_at, not_none())
            connection.sync_retry_at = None
            session.add(connection)
            session.commit()

        context.injector.get(FileSyncEngine).run_pass(datetime.now(UTC))

        assert_that(_folders(context), equal_to([]))
        assert_that(_provider_folders(context), equal_to([]))


def test_a_failed_folder_delete_does_not_hold_up_other_agents(monkeypatch: pytest.MonkeyPatch):
    with given(_BASE) as context:
        retired = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        _update_agent(context, retired, deleted_at=datetime.now(UTC))
        newcomer = _agent(context, "Support")
        plugin = fake_drive(context)
        delete = plugin.delete_item
        failures = [ProviderUnavailable("Test Drive is down.")]

        def delete_item(root, *, item_id: str) -> None:
            if failures:
                raise failures.pop()
            delete(root, item_id=item_id)

        monkeypatch.setattr(plugin, "delete_item", delete_item)

        _reconcile(context)

        assert_that(_folder(context, retired).status, equal_to(SyncFolderStatus.RETIRED))
        assert_that(_folder(context, newcomer).folder_item_id, not_none())
        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Support"))

        _reconcile(context)

        assert_that(_provider_folders(context), equal_to(["Support"]))
        assert_that([folder.agent_id for folder in _folders(context)], equal_to([newcomer.id]))


def test_a_retired_agents_disabled_folder_is_deleted_too():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(SyncAgentFolder, _folder(context, agent).id)
            assert row is not None
            row.status = SyncFolderStatus.DISABLED
            session.add(row)
            session.commit()

        _update_agent(context, agent, deleted_at=datetime.now(UTC))
        _reconcile(context)

        assert_that(_folders(context), equal_to([]))
        assert_that(_provider_folders(context), equal_to([]))


def test_the_change_feed_reporting_the_deletion_later_rebuilds_nothing():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        engine = context.injector.get(FileSyncEngine)
        engine.run_pass(datetime.now(UTC))
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/notes.md", b"hello")
        engine.run_pass(datetime.now(UTC))
        calls_before = len(fake_drive(context).calls)

        _update_agent(context, agent, deleted_at=datetime.now(UTC))
        engine.run_pass(datetime.now(UTC))
        engine.run_pass(datetime.now(UTC))

        assert_that(_folders(context), equal_to([]))
        assert_that(_provider_folders(context), equal_to([]))
        assert_that("create_folder" in fake_drive(context).calls[calls_before:], equal_to(False))
        assert_that("move_item" in fake_drive(context).calls[calls_before:], equal_to(False))


def test_a_folder_with_sync_turned_off_is_left_alone():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        _reconcile(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(SyncAgentFolder, _folder(context, agent).id)
            assert row is not None
            row.status = SyncFolderStatus.DISABLED
            session.add(row)
            session.commit()

        _update_agent(context, agent, name="Sales Team")
        _reconcile(context)

        assert_that(_folder(context, agent).folder_name, equal_to("Sales Bot"))
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))


def test_a_name_already_used_at_the_provider_gets_a_number():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/someone else.md", b"x")

        _reconcile(context)

        assert_that(_folder(context, agent).folder_name, equal_to("Sales Bot (2)"))
        assert_that(_provider_folders(context), contains_inanyorder("Sales Bot", "Sales Bot (2)"))


def test_a_folder_the_provider_failed_to_create_is_created_on_the_next_pass():
    with given(_BASE) as context:
        agent = _agent(context, "Sales Bot")
        there_is_a_sync_connection()(context)
        fake_drive(context).throttle_next(120)

        with pytest.raises(ProviderThrottled):
            _reconcile(context)
        reserved = _folder(context, agent)
        _reconcile(context)

        assert_that((reserved.folder_name, reserved.folder_item_id), equal_to(("Sales Bot", None)))
        assert_that(_folder(context, agent).folder_item_id, not_none())
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))


def test_a_connection_whose_provider_has_no_file_sync_is_skipped():
    with given(_BASE) as context:
        _agent(context, "Sales Bot")
        there_is_a_sync_connection(provider_key=OTHER_DRIVE)(context)

        _reconcile(context)

        assert_that(_folders(context), has_length(0))


def test_another_organizations_agents_never_get_a_folder_here():
    with given(_BASE) as context:
        ours = _agent(context, "Sales Bot")
        own_org = context.organization
        there_is_an_organization(name="Other Org")(context)
        _agent(context, "Their Bot")
        context.organization = own_org
        there_is_a_sync_connection()(context)

        _reconcile(context)

        assert_that([folder.agent_id for folder in _folders(context)], equal_to([ours.id]))
        assert_that(_provider_folders(context), equal_to(["Sales Bot"]))
