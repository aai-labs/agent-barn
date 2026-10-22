import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import Agent, AgentType
from api.domains.file_sync.engine import sync_root
from api.domains.file_sync.models import (
    FileSyncChangesCreate,
    FileSyncChangesRead,
    FileSyncEntryCreate,
    FileSyncUploadRead,
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
)
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.file_sync.rules import MAX_FILE_BYTES, SyncCategory, classify, name_problem, path_too_long
from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.base import (
    ProviderThrottled,
    RemoteItemMissing,
    SyncProviderError,
    SyncProviderPlugin,
    SyncRoot,
)
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.infrastructure.crypto import decrypt_token

UPLOAD_REISSUE_AFTER = timedelta(minutes=14)
THROTTLE_FALLBACK_SECONDS = 60


class FileSyncUnauthorized(Exception):
    pass


class FileSyncNotFound(Exception):
    pass


class FileSyncConflict(Exception):
    pass


class FileSyncPathRefused(Exception):
    pass


class FileSyncProviderBusy(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"The provider asked to wait {retry_after}s")
        self.retry_after = retry_after


class FileSyncProviderFailed(Exception):
    pass


@dataclass(frozen=True)
class FileSyncTarget:
    agent: Agent
    connection: SyncProviderConnection
    folder: SyncAgentFolder
    plugin: SyncProviderPlugin
    root: SyncRoot
    folder_item_id: str


@inject
@singleton
@dataclass
class FileSyncIngestService:
    repository: FileSyncRepository
    plugins: SyncProviderPluginRegistry
    config: Config

    def report_changes(self, agent_id: UUID, provided_key: str, changes: FileSyncChangesCreate) -> FileSyncChangesRead:
        target = self._target(agent_id, provided_key)
        for entry in changes.entries:
            self._require_allowed(target, entry.path)
        now = datetime.now(UTC)
        known = {row.path.lower(): row for row in self.repository.files(target.folder.id)}
        seen: set[str] = set()
        uploads: list[FileSyncUploadRead] = []
        try:
            for entry in changes.entries:
                if self._skipped(target, entry, seen, now):
                    continue
                upload = self._sync_entry(target, entry, known.get(entry.path.lower()), now)
                if upload is not None:
                    uploads.append(upload)
        except ProviderThrottled as exc:
            raise FileSyncProviderBusy(exc.retry_after or THROTTLE_FALLBACK_SECONDS) from exc
        except SyncProviderError as exc:
            raise FileSyncProviderFailed(exc.message) from exc
        return FileSyncChangesRead(uploads=uploads)

    def complete_upload(self, agent_id: UUID, provided_key: str, path: str) -> None:
        target = self._target(agent_id, provided_key)
        self._require_allowed(target, path)
        row = self.repository.file_at(target.folder.id, path)
        if row is None or row.upload_started_at is None:
            raise FileSyncConflict("No upload is under way for this path")
        try:
            item = target.plugin.get_item_by_path(target.root, parent_id=target.folder_item_id, rel_path=path)
        except RemoteItemMissing as exc:
            raise FileSyncConflict("The upload has not reached the provider") from exc
        except ProviderThrottled as exc:
            raise FileSyncProviderBusy(exc.retry_after or THROTTLE_FALLBACK_SECONDS) from exc
        except SyncProviderError as exc:
            raise FileSyncProviderFailed(exc.message) from exc
        if item.is_folder or item.size != row.size:
            raise FileSyncConflict("The provider holds a different file at this path")
        self.repository.record_synced(
            target.folder.id, path, item, sha256=row.local_sha256, size=row.size, now=datetime.now(UTC)
        )

    def _skipped(self, target: FileSyncTarget, entry: FileSyncEntryCreate, seen: set[str], now: datetime) -> bool:
        kind = None
        if entry.size > MAX_FILE_BYTES:
            kind = SyncActivityKind.SKIPPED_TOO_LARGE
        elif (
            entry.path.lower() in seen
            or name_problem(entry.path) is not None
            or path_too_long(target.folder.folder_path or "", entry.path)
        ):
            kind = SyncActivityKind.SKIPPED_NAME
        seen.add(entry.path.lower())
        if kind is None:
            return False
        self.repository.record_activity_once(target.folder, kind, entry.path, entry.sha256, now)
        return True

    def _sync_entry(
        self, target: FileSyncTarget, entry: FileSyncEntryCreate, known: SyncFile | None, now: datetime
    ) -> FileSyncUploadRead | None:
        if known is not None and known.local_sha256 == entry.sha256:
            if known.upload_started_at is None and known.synced_at is not None:
                return None
            if known.upload_started_at is not None and now - known.upload_started_at < UPLOAD_REISSUE_AFTER:
                return None
        if entry.size == 0:
            item = target.plugin.write_empty_file(target.root, parent_id=target.folder_item_id, rel_path=entry.path)
            self.repository.record_synced(target.folder.id, entry.path, item, sha256=entry.sha256, size=0, now=now)
            return None
        upload = target.plugin.upload_target(target.root, parent_id=target.folder_item_id, rel_path=entry.path)
        self.repository.start_upload(target.folder.id, entry.path, sha256=entry.sha256, size=entry.size, now=now)
        return FileSyncUploadRead(path=entry.path, url=upload.url, expires_at=upload.expires_at)

    @staticmethod
    def _require_allowed(target: FileSyncTarget, path: str) -> None:
        runtime = AgentType(target.agent.agent_type).value
        if unicodedata.normalize("NFC", path) != path or classify(runtime, path) == SyncCategory.NEVER:
            raise FileSyncPathRefused(f"Path not synced: {path!r}")

    def _target(self, agent_id: UUID, provided_key: str) -> FileSyncTarget:
        agent = self.repository.agent_including_deleted(agent_id)
        if agent is None or not agent.ingest_key_encrypted or not provided_key:
            raise FileSyncUnauthorized()
        stored_key = decrypt_token(agent.ingest_key_encrypted, self.config.agent_token_encryption_key)
        if not secrets.compare_digest(stored_key, provided_key):
            raise FileSyncUnauthorized()
        if agent.deleted_at is not None:
            raise FileSyncNotFound("Agent not found")
        connection, folder = self.repository.agent_sync_target(agent.organization_id, agent.id)
        if connection is None:
            raise FileSyncConflict("The Organization has no active sync connection")
        plugin = self.plugins.require(connection.provider_key)
        root = sync_root(connection)
        if SyncProviderCapability.FILE_SYNC not in plugin.capabilities or root is None:
            raise FileSyncConflict("The connected provider does not sync Agent files")
        if folder is None:
            raise FileSyncNotFound("The Agent's folder does not exist yet")
        if folder.status != SyncFolderStatus.ACTIVE:
            raise FileSyncConflict("File sync is turned off for this Agent")
        if folder.folder_item_id is None:
            raise FileSyncConflict("The Agent's folder is still being created")
        self.repository.touch_folder(folder.id, datetime.now(UTC))
        return FileSyncTarget(
            agent=agent,
            connection=connection,
            folder=folder,
            plugin=plugin,
            root=root,
            folder_item_id=folder.folder_item_id,
        )
