import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, none

from api.domains.sync_provider.models import SyncProviderCapability
from api.domains.sync_provider.plugins.base import (
    ProviderThrottled,
    RemoteItemMissing,
    RemoteNameTaken,
    RemoteResyncRequired,
    SyncRoot,
)
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.tests.steps.file_sync_provider import TEST_DRIVE, TestDrivePlugin
from api.tests.steps.sync_provider import OtherDrivePlugin


def _connected() -> tuple[TestDrivePlugin, SyncRoot]:
    plugin = TestDrivePlugin()
    provisioned = plugin.provision("token", account_id="account-1", location=None, folder_name="Agent Barn")
    root = SyncRoot(account_id="account-1", location_id=None, folder_id=provisioned.folder.id, folder_name="Agent Barn")
    return plugin, root


def test_the_registry_accepts_it_as_a_file_sync_provider():
    registry = SyncProviderPluginRegistry([TestDrivePlugin(), OtherDrivePlugin()])

    assert_that(SyncProviderCapability.FILE_SYNC in registry.require(TEST_DRIVE).capabilities, is_(True))
    assert_that(SyncProviderCapability.FILE_SYNC in registry.require("otherdrive").capabilities, is_(False))


def test_items_carry_their_path_inside_the_root():
    plugin, root = _connected()
    folder = plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")

    plugin.user_adds(root, "Sales Bot/workspace/notes.md", b"hello")
    item = plugin.get_item_by_path(root, parent_id=folder.id, rel_path="workspace/notes.md")

    assert_that((folder.path, folder.is_folder), equal_to(("Sales Bot", True)))
    assert_that(
        (item.path, item.name, item.size, item.modified_by_app),
        equal_to(("Sales Bot/workspace/notes.md", "notes.md", 5, False)),
    )
    assert_that(plugin.get_item(root, item_id=root.folder_id).path, none())


def test_a_name_already_taken_in_any_case_is_refused():
    plugin, root = _connected()
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")

    with pytest.raises(RemoteNameTaken):
        plugin.create_folder(root, parent_id=root.folder_id, name="sales bot")


def test_a_content_edit_changes_both_versions_and_a_rename_only_the_version():
    plugin, root = _connected()
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    first = plugin.user_adds(root, "Sales Bot/notes.md", b"v1")

    edited = plugin.user_edits(root, "Sales Bot/notes.md", b"v2 longer")
    renamed = plugin.move_item(root, item_id=first.id, name="renamed.md")

    assert_that(edited.content_version == first.content_version, is_(False))
    assert_that(edited.version == first.version, is_(False))
    assert_that(renamed.content_version, equal_to(edited.content_version))
    assert_that(renamed.version == edited.version, is_(False))
    assert_that((renamed.path, renamed.modified_by_app), equal_to(("Sales Bot/renamed.md", True)))


def test_a_deleted_item_is_missing_and_deleting_it_again_is_not_an_error():
    plugin, root = _connected()
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    item = plugin.user_adds(root, "Sales Bot/notes.md", b"x")

    plugin.delete_item(root, item_id=item.id)
    plugin.delete_item(root, item_id=item.id)

    with pytest.raises(RemoteItemMissing):
        plugin.get_item(root, item_id=item.id)


def test_changes_start_from_now_and_report_later_changes_with_deletions_pathless():
    plugin, root = _connected()
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    kept = plugin.user_adds(root, "Sales Bot/kept.md", b"x")
    gone = plugin.user_adds(root, "Sales Bot/gone.md", b"x")

    start = plugin.changes(root, None)
    plugin.user_edits(root, "Sales Bot/kept.md", b"edited")
    plugin.user_deletes(root, "Sales Bot/gone.md")
    later = plugin.changes(root, start.cursor)

    assert_that(start.items, equal_to([]))
    by_id = {item.id: item for item in later.items}
    assert_that(by_id[kept.id].path, equal_to("Sales Bot/kept.md"))
    assert_that((by_id[gone.id].deleted, by_id[gone.id].path), equal_to((True, None)))
    assert_that(by_id[gone.id].modified_by_app, equal_to(False))
    assert_that(plugin.changes(root, later.cursor).items, equal_to([]))


def test_changes_from_the_start_list_everything_under_the_root_in_pages():
    plugin, root = _connected()
    plugin.page_size = 2
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    plugin.user_adds(root, "Sales Bot/a.md", b"a")
    plugin.user_adds(root, "Sales Bot/b.md", b"b")

    first = plugin.changes(root, None, from_start=True)
    second = plugin.changes(root, first.cursor)

    assert_that((len(first.items), first.more), equal_to((2, True)))
    assert_that((len(second.items), second.more), equal_to((1, False)))
    assert_that(
        sorted(str(item.path) for item in [*first.items, *second.items]),
        equal_to(["Sales Bot", "Sales Bot/a.md", "Sales Bot/b.md"]),
    )


def test_an_expired_cursor_asks_for_a_resync():
    plugin, root = _connected()
    cursor = plugin.changes(root, None).cursor

    plugin.expire_cursors()

    with pytest.raises(RemoteResyncRequired):
        plugin.changes(root, cursor)


def test_a_cursor_from_a_fresh_listing_after_expiry_is_valid():
    plugin, root = _connected()
    plugin.changes(root, None)
    plugin.expire_cursors()

    fresh = plugin.changes(root, None, from_start=True).cursor

    assert_that(plugin.changes(root, fresh).items, equal_to([]))


def test_throttling_the_next_call_carries_the_wait_once():
    plugin, root = _connected()
    plugin.throttle_next(120)

    with pytest.raises(ProviderThrottled) as exc:
        plugin.get_item(root, item_id=root.folder_id)

    assert_that(exc.value.retry_after, equal_to(120))
    assert_that(plugin.get_item(root, item_id=root.folder_id).id, equal_to(root.folder_id))


def test_throttling_one_kind_of_call_leaves_the_others_alone():
    plugin, root = _connected()
    plugin.throttle_call("move_item", 45)
    folder = plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")

    with pytest.raises(ProviderThrottled) as exc:
        plugin.move_item(root, item_id=folder.id, name="Renamed")

    assert_that(exc.value.retry_after, equal_to(45))
    assert_that(plugin.move_item(root, item_id=folder.id, name="Renamed").path, equal_to("Renamed"))


def test_an_upload_lands_only_when_the_pod_completes_it_and_replaces_the_file():
    plugin, root = _connected()
    folder = plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    old = plugin.user_adds(root, "Sales Bot/workspace/notes.md", b"user")

    target = plugin.upload_target(root, parent_id=folder.id, rel_path="workspace/notes.md")
    before = plugin.get_item(root, item_id=old.id)
    uploaded = plugin.complete_upload(target.url, b"agent copy")

    assert_that(before.content_version, equal_to(old.content_version))
    assert_that(target.url, contains_string("https://testdrive.example.test/upload/"))
    assert_that((uploaded.id, uploaded.size, uploaded.modified_by_app), equal_to((old.id, 10, True)))
    assert_that(uploaded.content_version == old.content_version, is_(False))


def test_downloads_and_empty_files_need_no_upload():
    plugin, root = _connected()
    folder = plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    item = plugin.user_adds(root, "Sales Bot/notes.md", b"x")

    url = plugin.download_url(root, item_id=item.id)
    empty = plugin.write_empty_file(root, parent_id=folder.id, rel_path="workspace/empty.txt")

    assert_that(plugin.content_at(url), equal_to(b"x"))
    assert_that((empty.path, empty.size), equal_to(("Sales Bot/workspace/empty.txt", 0)))


def test_a_user_move_out_of_the_root_leaves_the_item_without_a_path():
    plugin, root = _connected()
    plugin.create_folder(root, parent_id=root.folder_id, name="Sales Bot")
    item = plugin.user_adds(root, "Sales Bot/notes.md", b"x")

    cursor = plugin.changes(root, None).cursor
    moved = plugin.user_moves_outside(root, "Sales Bot/notes.md")
    reported = {change.id: change for change in plugin.changes(root, cursor).items}

    assert_that((moved.id, moved.path, moved.deleted), equal_to((item.id, None, False)))
    assert_that((reported[item.id].deleted, reported[item.id].path), equal_to((True, None)))
