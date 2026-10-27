import logging
import secrets
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
    FileSyncOperationOutcome,
    FileSyncOperationRead,
    FileSyncOperationResultCreate,
    FileSyncOperationsRead,
    FileSyncUploadRead,
    SyncActivityKind,
    SyncAgentFolder,
    SyncFile,
    SyncFolderStatus,
    SyncPendingAction,
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

logger = logging.getLogger(__name__)

UPLOAD_REISSUE_AFTER = timedelta(minutes=14)
UPLOAD_CLOCK_SKEW = timedelta(minutes=2)
THROTTLE_FALLBACK_SECONDS = 60
OPERATION_LEASE = timedelta(minutes=3)
NO_SPACE_RETRY = timedelta(minutes=5)
FAILED_RETRY_BASE_SECONDS = 60
FAILED_RETRY_MAX_SECONDS = 1800
DISCONNECT_LOCK_WAIT_SECONDS = 15


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


class FileSyncBusy(Exception):
    pass


@dataclass(frozen=True)
class FileSyncTarget:
    agent: Agent
    connection: SyncProviderConnection
    folder: SyncAgentFolder
    plugin: SyncProviderPlugin
    root: SyncRoot
    folder_item_id: str


def _provider_failed(target: FileSyncTarget, exc: SyncProviderError) -> FileSyncProviderFailed:
    logger.warning(
        "File sync for Agent %s failed at the provider: %s: %s", target.agent.id, type(exc).__name__, exc.message
    )
    return FileSyncProviderFailed(exc.message)


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
        for entry in changes.entries:
            if self._skipped(target, entry, seen, now):
                continue
            upload = self._per_file(
                target,
                entry.path,
                lambda entry=entry: self._sync_entry(target, entry, known.get(entry.path.lower()), now),
            )
            if upload is not None:
                uploads.append(upload)
        if changes.complete and changes.entries:
            for lowered, row in known.items():
                if lowered not in seen:
                    self._per_file(target, row.path, lambda row=row: self._delete_missing(target, row, now))
        return FileSyncChangesRead(uploads=uploads)

    def _per_file[T](self, target: FileSyncTarget, path: str, action: Callable[[], T]) -> T | None:
        try:
            return action()
        except ProviderThrottled as exc:
            raise FileSyncProviderBusy(exc.retry_after or THROTTLE_FALLBACK_SECONDS) from exc
        except SyncProviderError as exc:
            logger.warning(
                "File sync skipped %s for Agent %s this round: %s: %s",
                path,
                target.agent.id,
                type(exc).__name__,
                exc.message,
            )
            return None

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
            raise _provider_failed(target, exc) from exc
        started = row.upload_started_at - UPLOAD_CLOCK_SKEW
        if item.is_folder or not item.modified_by_app or (item.modified_at is not None and item.modified_at < started):
            raise FileSyncConflict("The provider holds a file this upload didn't write")
        now = datetime.now(UTC)
        self.repository.record_synced(target.folder.id, path, item, sha256=row.local_sha256, size=row.size, now=now)
        if row.pending_activity is not None:
            self.repository.record_activity(target.folder, row.pending_activity, row.path, now)

    def claim_operations(self, agent_id: UUID, provided_key: str) -> FileSyncOperationsRead:
        target = self._target(agent_id, provided_key)
        now = datetime.now(UTC)
        claimed = self.repository.claim_operations(target.folder.id, now, now + OPERATION_LEASE)
        operations: list[FileSyncOperationRead] = []
        try:
            for row in claimed:
                operation = self._hand_out(target, row, now)
                if operation is not None:
                    operations.append(operation)
        except ProviderThrottled as exc:
            for row in claimed:
                self.repository.release(row.id, None)
            raise FileSyncProviderBusy(exc.retry_after or THROTTLE_FALLBACK_SECONDS) from exc
        except SyncProviderError as exc:
            for row in claimed:
                self.repository.release(row.id, None)
            raise _provider_failed(target, exc) from exc
        return FileSyncOperationsRead(operations=operations)

    def report_result(self, agent_id: UUID, provided_key: str, result: FileSyncOperationResultCreate) -> None:
        target = self._target(agent_id, provided_key)
        self._require_allowed(target, result.path)
        row = self.repository.file_at(target.folder.id, result.path)
        if row is None or row.pending is None or row.lease_until is None:
            raise FileSyncConflict("No job was handed out for this path")
        now = datetime.now(UTC)
        match result.outcome:
            case FileSyncOperationOutcome.DONE:
                self._finish_download(target, row, result, now)
            case FileSyncOperationOutcome.SKIPPED_NO_SPACE:
                detail = result.version or row.ctag or ""
                self.repository.record_activity_once(
                    target.folder, SyncActivityKind.SKIPPED_NO_SPACE, row.path, detail, now
                )
                self.repository.release(row.id, now + NO_SPACE_RETRY)
            case FileSyncOperationOutcome.FAILED:
                wait = min(FAILED_RETRY_BASE_SECONDS * 2 ** max(row.attempts - 1, 0), FAILED_RETRY_MAX_SECONDS)
                self.repository.release(row.id, now + timedelta(seconds=wait))
            case FileSyncOperationOutcome.LOCAL_CHANGED:
                self.repository.clear_pending(row.id)
                self.repository.record_activity(target.folder, SyncActivityKind.CONFLICT_AGENT_WON, row.path, now)

    def _hand_out(self, target: FileSyncTarget, row: SyncFile, now: datetime) -> FileSyncOperationRead | None:
        if row.pending == SyncPendingAction.REUPLOAD:
            upload = target.plugin.upload_target(target.root, parent_id=target.folder_item_id, rel_path=row.path)
            self.repository.start_upload(target.folder.id, row.path, sha256=row.local_sha256, size=row.size, now=now)
            return FileSyncOperationRead(
                path=row.path,
                action=SyncPendingAction.REUPLOAD,
                url=upload.url,
                expires_at=upload.expires_at,
                version=None,
            )
        if row.item_id is None:
            self.repository.clear_pending(row.id)
            return None
        try:
            item = target.plugin.get_item(target.root, item_id=row.item_id)
        except RemoteItemMissing:
            self.repository.clear_pending(row.id)
            return None
        url = target.plugin.download_url(target.root, item_id=row.item_id)
        return FileSyncOperationRead(
            path=row.path, action=SyncPendingAction.DOWNLOAD, url=url, expires_at=None, version=item.content_version
        )

    def _finish_download(
        self, target: FileSyncTarget, row: SyncFile, result: FileSyncOperationResultCreate, now: datetime
    ) -> None:
        if row.pending != SyncPendingAction.DOWNLOAD or row.item_id is None:
            raise FileSyncConflict("Only a download is finished with a done result")
        try:
            item = target.plugin.get_item(target.root, item_id=row.item_id)
        except RemoteItemMissing:
            self.repository.clear_pending(row.id)
            return
        except ProviderThrottled as exc:
            raise FileSyncProviderBusy(exc.retry_after or THROTTLE_FALLBACK_SECONDS) from exc
        except SyncProviderError as exc:
            raise _provider_failed(target, exc) from exc
        if item.content_version != result.version:
            self.repository.requeue_download(row.id)
            return
        if result.sha256 is None or result.size is None:
            raise FileSyncConflict("A done result names the written content")
        self.repository.record_synced(target.folder.id, row.path, item, sha256=result.sha256, size=result.size, now=now)

    def _delete_missing(self, target: FileSyncTarget, row: SyncFile, now: datetime) -> None:
        if row.item_id is not None:
            target.plugin.delete_item(target.root, item_id=row.item_id)
            self.repository.record_activity(target.folder, SyncActivityKind.DELETED_BY_AGENT, row.path, now)
        self.repository.remove_file(row.id)

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
        if known is not None and known.pending == SyncPendingAction.DOWNLOAD:
            self.repository.clear_pending(known.id)
            self.repository.record_activity(target.folder, SyncActivityKind.CONFLICT_AGENT_WON, known.path, now)
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
        if not secrets.compare_digest(stored_key.encode(), provided_key.encode()):
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
            raise FileSyncConflict("File sync is not ready for this Agent yet")
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


@inject
@singleton
@dataclass
class FileSyncFolderRemoval:
    repository: FileSyncRepository

    @contextmanager
    def holding(self, connection_id: UUID) -> Iterator[None]:
        with self.repository.connection_lock(connection_id, wait_seconds=DISCONNECT_LOCK_WAIT_SECONDS) as acquired:
            if not acquired:
                raise FileSyncBusy
            yield

    def remove_agent_folders(self, connection: SyncProviderConnection, plugin: SyncProviderPlugin, token: str) -> None:
        root = sync_root(connection)
        for folder in self.repository.folders(connection.id):
            if root is not None and folder.folder_item_id is not None:
                try:
                    plugin.delete_item_with(token, root, item_id=folder.folder_item_id)
                except RemoteItemMissing:
                    pass
                except SyncProviderError as exc:
                    logger.warning(
                        "Disconnect left the folder of Agent %s at the provider: %s: %s",
                        folder.agent_id,
                        type(exc).__name__,
                        exc.message,
                    )
            self.repository.remove_folder(folder.id)
