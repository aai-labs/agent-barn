import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton

from api.domains.file_sync.models import SyncActivityKind, SyncAgentFolder, SyncFolderStatus, SyncPendingAction
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.file_sync.rules import FORBIDDEN_CHARACTERS, MAX_FILE_BYTES, SyncCategory, classify, name_problem
from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.base import (
    ProviderThrottled,
    RemoteItem,
    RemoteNameTaken,
    SyncProviderPlugin,
    SyncRoot,
)
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.domains.sync_provider.service import FOLDER_NAME

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
        folders = {
            folder.folder_name.lower(): (folder, runtime)
            for folder, runtime in self.repository.folders_with_runtime(connection.id)
            if folder.status == SyncFolderStatus.ACTIVE and folder.folder_item_id is not None
        }
        cursor = connection.sync_cursor
        while True:
            page = plugin.changes(root, cursor)
            for item in page.items:
                self._remote_change(folders, item)
            cursor = page.cursor
            self.repository.save_cursor(connection.id, cursor)
            if not page.more:
                return

    def _remote_change(self, folders: dict[str, tuple[SyncAgentFolder, str]], item: RemoteItem) -> None:
        if item.is_folder or item.deleted or item.path is None:
            return
        folder_name, _, rel_path = item.path.partition("/")
        entry = folders.get(folder_name.lower())
        if not rel_path or entry is None:
            return
        folder, runtime = entry
        row = self.repository.file_by_item(folder.id, item.id)
        if row is None or row.path.lower() != rel_path.lower():
            return
        if item.modified_by_app or row.upload_started_at is not None or item.content_version == row.ctag:
            return
        now = datetime.now(UTC)
        settle_at = (item.modified_at or now) + SETTLE_DELAY
        version = item.content_version or ""
        category = classify(runtime, rel_path)
        if category in (SyncCategory.WORK, SyncCategory.MEMORY):
            if item.size > MAX_FILE_BYTES:
                self.repository.record_activity_once(folder, SyncActivityKind.SKIPPED_TOO_LARGE, row.path, version, now)
                return
            self.repository.mark_remote_change(row.id, SyncPendingAction.DOWNLOAD, settle_at)
        elif category in (SyncCategory.CONFIG, SyncCategory.SKILLS):
            if self.repository.mark_remote_change(row.id, SyncPendingAction.REUPLOAD, settle_at):
                self.repository.record_activity_once(folder, SyncActivityKind.EDIT_UNDONE, row.path, version, now)

    def reconcile_folders(self, connection: SyncProviderConnection) -> None:
        plugin = self.plugins.require(connection.provider_key)
        root = sync_root(connection)
        if SyncProviderCapability.FILE_SYNC not in plugin.capabilities or root is None:
            return
        agents = self.repository.live_agent_names(connection.organization_id)
        live = {agent_id for agent_id, _ in agents}
        folders = self.repository.folders(connection.id)
        self.repository.stop_folders(
            [
                folder.id
                for folder in folders
                if folder.agent_id not in live and folder.status != SyncFolderStatus.STOPPED
            ]
        )
        by_agent = {folder.agent_id: folder for folder in folders}
        taken = {folder.folder_name.lower() for folder in folders}
        for agent_id, agent_name in agents:
            base = folder_base_name(agent_name)
            folder = by_agent.get(agent_id) or self._reserve(connection, agent_id, base, taken)
            if folder is None or folder.status != SyncFolderStatus.ACTIVE:
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
