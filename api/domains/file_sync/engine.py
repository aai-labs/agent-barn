import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton

from api.domains.file_sync.models import (
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
    SyncPendingAction,
)
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.file_sync.rules import (
    FORBIDDEN_CHARACTERS,
    MAX_FILE_BYTES,
    NOT_SYNCED_DIR,
    SyncCategory,
    classify,
    name_problem,
)
from api.domains.sync_provider.models import FOLDER_NAME, SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.base import (
    ProviderThrottled,
    RemoteItem,
    RemoteItemMissing,
    RemoteNameTaken,
    RemoteResyncRequired,
    SyncProviderError,
    SyncProviderPlugin,
    SyncRoot,
)
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry

logger = logging.getLogger(__name__)

FOLDER_NAME_MAX = 255
THROTTLE_FALLBACK_SECONDS = 60
SETTLE_DELAY = timedelta(seconds=30)
FOLDER_NAME_FALLBACK = "Agent"
FOLDER_FORBIDDEN_CHARACTERS = FORBIDDEN_CHARACTERS | {"/"}
NAME_ATTEMPTS = 100
NUMBERED_NAME = re.compile(r"^(?P<base>.*) \((?P<number>[2-9]|[1-9][0-9]+)\)$")


def folder_base_name(agent_name: str) -> str:
    replaced = "".join("-" if char in FOLDER_FORBIDDEN_CHARACTERS or ord(char) < 32 else char for char in agent_name)
    name = replaced.strip().rstrip(". ").strip()
    if not name or name_problem(name) is not None:
        return FOLDER_NAME_FALLBACK
    return name[:FOLDER_NAME_MAX]


def numbered_name(base: str, number: int) -> str:
    if number == 1:
        return base[:FOLDER_NAME_MAX]
    suffix = f" ({number})"
    return f"{base[: FOLDER_NAME_MAX - len(suffix)]}{suffix}"


def _number_of(folder_name: str, base: str) -> int | None:
    if folder_name == numbered_name(base, 1):
        return 1
    match = NUMBERED_NAME.match(folder_name)
    if match and folder_name == numbered_name(base, int(match["number"])):
        return int(match["number"])
    return None


@dataclass(frozen=True)
class _Changes:
    connection: SyncProviderConnection
    plugin: SyncProviderPlugin
    root: SyncRoot
    by_name: dict[str, tuple[SyncAgentFolder, str]]
    by_item: dict[str, SyncAgentFolder]


@dataclass(frozen=True)
class _Target:
    folder: SyncAgentFolder
    runtime: str
    rel_path: str


def _locate(changes: _Changes, path: str | None) -> _Target | None:
    if path is None:
        return None
    folder_name, _, rel_path = path.partition("/")
    entry = changes.by_name.get(folder_name.lower())
    if entry is None or not rel_path or rel_path.split("/", 1)[0] == NOT_SYNCED_DIR:
        return None
    return _Target(folder=entry[0], runtime=entry[1], rel_path=rel_path)


def _changed_since(row: SyncFile, moment: datetime) -> bool:
    return any(at is not None and at >= moment for at in (row.synced_at, row.upload_started_at))


def delete_agent_folder(
    plugin: SyncProviderPlugin, root: SyncRoot | None, repository: FileSyncRepository, folder: SyncAgentFolder
) -> None:
    if root is not None and folder.folder_item_id is not None:
        try:
            plugin.delete_item(root, item_id=folder.folder_item_id)
        except RemoteItemMissing:
            pass
    repository.remove_folder(folder.id)


def sync_root(connection: SyncProviderConnection) -> SyncRoot | None:
    if connection.folder_id is None:
        return None
    return SyncRoot(
        account_id=connection.account_id,
        location_id=connection.location_id,
        folder_id=connection.folder_id,
        folder_name=FOLDER_NAME,
    )


def _server_path(web_url: str | None) -> str | None:
    return urllib.parse.unquote(urllib.parse.urlparse(web_url).path) if web_url else None


@inject
@singleton
@dataclass
class FileSyncEngine:
    repository: FileSyncRepository
    plugins: SyncProviderPluginRegistry

    def run_pass(self, now: datetime) -> None:
        for connection in self.repository.due_connections(now):
            with self.repository.connection_lock(connection.id) as acquired:
                if not acquired:
                    continue
                try:
                    self.reconcile_folders(connection)
                    self.process_changes(connection)
                except ProviderThrottled as exc:
                    wait = exc.retry_after or THROTTLE_FALLBACK_SECONDS
                    self.repository.postpone(connection.id, now + timedelta(seconds=wait))
                    logger.info("File sync for connection %s throttled for %ss", connection.id, wait)
                except Exception:
                    logger.exception("File sync pass failed for connection %s", connection.id)

    def process_changes(self, connection: SyncProviderConnection) -> None:
        plugin = self.plugins.require(connection.provider_key)
        root = sync_root(connection)
        if SyncProviderCapability.FILE_SYNC not in plugin.capabilities or root is None:
            return
        if connection.sync_cursor is None:
            self.repository.save_cursor(connection.id, plugin.changes(root, None).cursor)
            return
        active = [
            (folder, runtime)
            for folder, runtime in self.repository.folders_with_runtime(connection.id)
            if folder.status == SyncFolderStatus.ACTIVE and folder.folder_item_id is not None
        ]
        changes = _Changes(
            connection=connection,
            plugin=plugin,
            root=root,
            by_name={folder.folder_name.lower(): (folder, runtime) for folder, runtime in active},
            by_item={folder.folder_item_id: folder for folder, _ in active if folder.folder_item_id is not None},
        )
        requested = {
            folder.id: folder.resync_requested_at for folder, _ in active if folder.resync_requested_at is not None
        }
        try:
            if requested:
                self._relist(changes)
            else:
                self._follow(changes, connection.sync_cursor)
        except RemoteResyncRequired:
            self._relist(changes)
        self.repository.clear_resync(requested)

    def _follow(self, changes: _Changes, cursor: str) -> None:
        while True:
            page = changes.plugin.changes(changes.root, cursor)
            for item in page.items:
                self._remote_change(changes, item)
            cursor = page.cursor
            self.repository.save_cursor(changes.connection.id, cursor)
            if not page.more:
                return

    def _relist(self, changes: _Changes) -> None:
        started = datetime.now(UTC)
        seen: set[str] = set()
        cursor: str | None = None
        while True:
            page = changes.plugin.changes(changes.root, cursor, from_start=cursor is None)
            for item in page.items:
                if not item.deleted:
                    seen.add(item.id)
                self._remote_change(changes, item)
            cursor = page.cursor
            if not page.more:
                break
        now = datetime.now(UTC)
        for folder_item_id, folder in changes.by_item.items():
            if folder_item_id not in seen:
                self._rebuild_folder(folder, now)
        for row, folder in self.repository.synced_files_in_connection(changes.connection.id):
            if _changed_since(row, started):
                continue
            if row.item_id not in seen and folder.folder_item_id in changes.by_item and folder.folder_item_id in seen:
                self.repository.restore_from_agent(row.id)
        self.repository.save_cursor(changes.connection.id, cursor)

    def _remote_change(self, changes: _Changes, item: RemoteItem) -> None:
        if item.modified_by_app:
            return
        if item.is_folder:
            self._folder_change(changes, item)
            return
        target = _locate(changes, None if item.deleted else item.path)
        tracked = self.repository.file_by_item_in_connection(changes.connection.id, item.id)
        if tracked is not None:
            row, folder = tracked
            if folder.status != SyncFolderStatus.ACTIVE:
                return
            in_own_folder = target is not None and target.folder.id == folder.id
            if in_own_folder and target is not None and target.rel_path.lower() == row.path.lower():
                self._content_edit(target, row, item)
                return
            if in_own_folder and self._move_back(changes, folder, row, item):
                return
            self.repository.restore_from_agent(row.id)
            if target is not None:
                self._park(changes, target, item)
            return
        if item.deleted or target is None:
            return
        at_path = self.repository.file_at(target.folder.id, target.rel_path)
        if at_path is None:
            self._park(changes, target, item)
            return
        if at_path.upload_started_at is not None:
            return
        self.repository.adopt_item(at_path.id, item.id)
        at_path.item_id = item.id
        at_path.pending = None
        self._content_edit(target, at_path, item)

    def _content_edit(self, target: _Target, row: SyncFile, item: RemoteItem) -> None:
        if row.upload_started_at is not None or item.content_version == row.ctag:
            return
        now = datetime.now(UTC)
        settle_at = (item.modified_at or now) + SETTLE_DELAY
        version = item.content_version or ""
        category = classify(target.runtime, target.rel_path)
        if category in (SyncCategory.WORK, SyncCategory.MEMORY):
            if item.size > MAX_FILE_BYTES:
                self.repository.record_activity_once(
                    target.folder, SyncActivityKind.SKIPPED_TOO_LARGE, row.path, version, now
                )
                return
            self.repository.mark_remote_change(row.id, SyncPendingAction.DOWNLOAD, settle_at)
        elif category in (SyncCategory.CONFIG, SyncCategory.SKILLS):
            self.repository.mark_remote_change(
                row.id, SyncPendingAction.REUPLOAD, settle_at, note=SyncActivityKind.EDIT_UNDONE
            )

    def _move_back(self, changes: _Changes, folder: SyncAgentFolder, row: SyncFile, item: RemoteItem) -> bool:
        folder_item_id = folder.folder_item_id
        if folder_item_id is None:
            return False
        original_dir, _, original_name = row.path.rpartition("/")
        try:
            parent_id = (
                changes.plugin.get_item_by_path(changes.root, parent_id=folder_item_id, rel_path=original_dir).id
                if original_dir
                else folder_item_id
            )
            changes.plugin.move_item(changes.root, item_id=item.id, name=original_name, parent_id=parent_id)
        except RemoteItemMissing, RemoteNameTaken:
            return False
        self.repository.record_activity(folder, SyncActivityKind.RENAMED_BACK, row.path, datetime.now(UTC))
        return True

    def _park(self, changes: _Changes, target: _Target, item: RemoteItem) -> None:
        folder_item_id = target.folder.folder_item_id
        if folder_item_id is None or item.name is None:
            return
        not_synced = self._not_synced_folder(changes, folder_item_id)
        stem, dot, extension = item.name.rpartition(".")
        if not stem:
            stem, dot, extension = item.name, "", ""
        for number in range(1, NAME_ATTEMPTS + 1):
            name = item.name if number == 1 else f"{stem} ({number}){dot}{extension}"
            try:
                changes.plugin.move_item(changes.root, item_id=item.id, name=name, parent_id=not_synced)
                break
            except RemoteNameTaken:
                continue
            except RemoteItemMissing:
                return
        self.repository.record_activity(
            target.folder, SyncActivityKind.MOVED_NOT_SYNCED, target.rel_path, datetime.now(UTC)
        )

    def _not_synced_folder(self, changes: _Changes, folder_item_id: str) -> str:
        try:
            return changes.plugin.get_item_by_path(changes.root, parent_id=folder_item_id, rel_path=NOT_SYNCED_DIR).id
        except RemoteItemMissing:
            pass
        try:
            return changes.plugin.create_folder(changes.root, parent_id=folder_item_id, name=NOT_SYNCED_DIR).id
        except RemoteNameTaken:
            return changes.plugin.get_item_by_path(changes.root, parent_id=folder_item_id, rel_path=NOT_SYNCED_DIR).id

    def _folder_change(self, changes: _Changes, item: RemoteItem) -> None:
        folder = changes.by_item.get(item.id)
        if folder is None:
            return
        now = datetime.now(UTC)
        if not item.deleted and item.path == folder.folder_name:
            return
        if not item.deleted and item.path is not None:
            try:
                changes.plugin.move_item(
                    changes.root, item_id=item.id, name=folder.folder_name, parent_id=changes.root.folder_id
                )
                self.repository.record_activity(folder, SyncActivityKind.FOLDER_RESTORED, None, now)
                return
            except RemoteItemMissing, RemoteNameTaken:
                pass
        self._rebuild_folder(folder, now)

    def _rebuild_folder(self, folder: SyncAgentFolder, now: datetime) -> None:
        self.repository.forget_folder_item(folder.id)
        self.repository.restore_folder_files(folder.id)
        self.repository.record_activity(folder, SyncActivityKind.FOLDER_RESTORED, None, now)

    def reconcile_folders(self, connection: SyncProviderConnection) -> None:
        plugin = self.plugins.require(connection.provider_key)
        root = sync_root(connection)
        if SyncProviderCapability.FILE_SYNC not in plugin.capabilities or root is None:
            return
        agents = self.repository.live_agent_names(connection.organization_id)
        live = {agent_id for agent_id, _, _ in agents}
        folders = self.repository.folders(connection.id)
        retired = [folder for folder in folders if folder.agent_id not in live]
        self.repository.retire_folders([folder.id for folder in retired if folder.status != SyncFolderStatus.RETIRED])
        gone = set()
        for folder in retired:
            try:
                delete_agent_folder(plugin, root, self.repository, folder)
            except ProviderThrottled:
                raise
            except SyncProviderError:
                logger.exception("Could not delete a retired Agent's folder; retrying on the next pass")
                continue
            gone.add(folder.id)
        folders = [folder for folder in folders if folder.id not in gone]
        by_agent = {folder.agent_id: folder for folder in folders}
        taken = {folder.folder_name.lower() for folder in folders}
        for agent_id, agent_name, sync_enabled in agents:
            base = folder_base_name(agent_name)
            folder = by_agent.get(agent_id)
            if folder is None and sync_enabled:
                folder = self._reserve(connection, agent_id, base, taken)
            if folder is None:
                continue
            if not sync_enabled and folder.status == SyncFolderStatus.ACTIVE:
                self.repository.set_folder_status(folder.id, SyncFolderStatus.DISABLED)
                continue
            if sync_enabled and folder.status == SyncFolderStatus.DISABLED:
                self.repository.resume_folder(folder.id, datetime.now(UTC))
                folder.status = SyncFolderStatus.ACTIVE
            if folder.status != SyncFolderStatus.ACTIVE:
                continue
            if folder.folder_item_id is None:
                self._create(plugin, root, folder, base, taken)
            else:
                self._follow_name(plugin, root, folder, base, taken)

    def _reserve(
        self, connection: SyncProviderConnection, agent_id: UUID, base: str, taken: set[str]
    ) -> SyncAgentFolder | None:
        for number in range(1, NAME_ATTEMPTS + 1):
            name = numbered_name(base, number)
            if name.lower() in taken:
                continue
            taken.add(name.lower())
            folder = self.repository.reserve_folder(connection, agent_id, name)
            if folder is not None:
                return folder
        return None

    def _create(
        self, plugin: SyncProviderPlugin, root: SyncRoot, folder: SyncAgentFolder, base: str, taken: set[str]
    ) -> None:
        name = folder.folder_name
        for _ in range(NAME_ATTEMPTS):
            try:
                item = plugin.create_folder(root, parent_id=root.folder_id, name=name)
            except RemoteNameTaken:
                name = self._rename_reserved(folder, name, base, taken)
                if name is None:
                    return
                continue
            self.repository.record_folder(
                folder.id, item_id=item.id, web_url=item.web_url, path=_server_path(item.web_url)
            )
            return

    def _follow_name(
        self, plugin: SyncProviderPlugin, root: SyncRoot, folder: SyncAgentFolder, base: str, taken: set[str]
    ) -> None:
        number = _number_of(folder.folder_name, base)
        others = taken - {folder.folder_name.lower()}
        if number == 1 or (number is not None and base.lower() in others):
            return
        name: str | None = self._free_name(base, others)
        while name is not None and folder.folder_item_id is not None:
            if not self.repository.rename_folder(folder.id, name):
                return
            taken.discard(folder.folder_name.lower())
            taken.add(name.lower())
            try:
                plugin.move_item(root, item_id=folder.folder_item_id, name=name)
                return
            except RemoteNameTaken:
                folder.folder_name = name
                name = self._free_name(base, taken)

    def _rename_reserved(self, folder: SyncAgentFolder, refused: str, base: str, taken: set[str]) -> str | None:
        taken.add(refused.lower())
        name = self._free_name(base, taken)
        while name is not None:
            taken.add(name.lower())
            if self.repository.rename_folder(folder.id, name):
                return name
            name = self._free_name(base, taken)
        return None

    @staticmethod
    def _free_name(base: str, taken: set[str]) -> str | None:
        for number in range(1, NAME_ATTEMPTS + 1):
            name = numbered_name(base, number)
            if name.lower() not in taken:
                return name
        return None
