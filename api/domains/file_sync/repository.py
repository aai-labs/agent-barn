from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import or_, text
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
from api.domains.sync_provider.models import SyncProviderConnection, SyncProviderStatus
from api.domains.sync_provider.plugins.base import RemoteItem
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class FileSyncRepository:
    delegate: PostgresRepositoryDelegate

    def due_connections(self, now: datetime) -> list[SyncProviderConnection]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(SyncProviderConnection)
                    .where(
                        col(SyncProviderConnection.status) == SyncProviderStatus.ACTIVE,
                        col(SyncProviderConnection.folder_id).is_not(None),
                        or_(
                            col(SyncProviderConnection.sync_retry_at).is_(None),
                            col(SyncProviderConnection.sync_retry_at) <= now,
                        ),
                    )
                    .order_by(col(SyncProviderConnection.connected_at), col(SyncProviderConnection.id))
                )
            )

    def postpone(self, connection_id: UUID, until: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(SyncProviderConnection)
                .where(col(SyncProviderConnection.id) == connection_id)
                .values(sync_retry_at=until)
            )
            session.commit()

    @contextmanager
    def connection_lock(self, connection_id: UUID) -> Iterator[bool]:
        lock_key = f"file-sync-connection:{connection_id}"
        with Session(self.delegate.engine) as session:
            acquired = bool(
                session.scalar(text("SELECT pg_try_advisory_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
            )
            try:
                yield acquired
            finally:
                if acquired:
                    session.scalar(text("SELECT pg_advisory_unlock(hashtext(:lock_key))"), {"lock_key": lock_key})

    def agent_including_deleted(self, agent_id: UUID) -> Agent | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(Agent).where(col(Agent.id) == agent_id)).first()

    def agent_sync_target(
        self, organization_id: UUID, agent_id: UUID
    ) -> tuple[SyncProviderConnection | None, SyncAgentFolder | None]:
        with Session(self.delegate.engine) as session:
            connection = session.exec(
                select(SyncProviderConnection).where(
                    col(SyncProviderConnection.organization_id) == organization_id,
                    col(SyncProviderConnection.status) == SyncProviderStatus.ACTIVE,
                )
            ).first()
            if connection is None:
                return None, None
            folder = session.exec(
                select(SyncAgentFolder).where(
                    col(SyncAgentFolder.connection_id) == connection.id,
                    col(SyncAgentFolder.agent_id) == agent_id,
                )
            ).first()
            return connection, folder

    def touch_folder(self, folder_id: UUID, now: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(SyncAgentFolder).where(col(SyncAgentFolder.id) == folder_id).values(last_contact_at=now)
            )
            session.commit()

    def files(self, folder_id: UUID) -> list[SyncFile]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(SyncFile).where(col(SyncFile.folder_id) == folder_id)))

    def file_at(self, folder_id: UUID, path: str) -> SyncFile | None:
        with Session(self.delegate.engine) as session:
            return session.exec(self._file_at(folder_id, path)).first()

    def start_upload(self, folder_id: UUID, path: str, *, sha256: str, size: int, now: datetime) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(self._file_at(folder_id, path)).first()
            row = row or SyncFile(folder_id=folder_id, path=path, local_sha256=sha256, size=size)
            row.local_sha256 = sha256
            row.size = size
            row.upload_started_at = now
            session.add(row)
            session.commit()

    def record_synced(
        self, folder_id: UUID, path: str, item: RemoteItem, *, sha256: str, size: int, now: datetime
    ) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(self._file_at(folder_id, path)).first()
            row = row or SyncFile(folder_id=folder_id, path=path, local_sha256=sha256, size=size)
            row.item_id = item.id
            row.etag = item.version
            row.ctag = item.content_version
            row.remote_hash = item.content_hash
            row.local_sha256 = sha256
            row.size = size
            row.synced_at = now
            row.upload_started_at = None
            row.pending = None
            row.lease_until = None
            row.attempts = 0
            row.retry_at = None
            session.add(row)
            session.commit()

    def claim_operations(self, folder_id: UUID, now: datetime, lease_until: datetime) -> list[SyncFile]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            rows = list(
                session.exec(
                    select(SyncFile)
                    .where(
                        col(SyncFile.folder_id) == folder_id,
                        col(SyncFile.pending).is_not(None),
                        or_(col(SyncFile.lease_until).is_(None), col(SyncFile.lease_until) < now),
                        or_(col(SyncFile.retry_at).is_(None), col(SyncFile.retry_at) <= now),
                    )
                    .order_by(col(SyncFile.path))
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.lease_until = lease_until
                row.attempts += 1
                session.add(row)
            session.commit()
            return rows

    def clear_pending(self, file_id: UUID) -> None:
        self._update_file(file_id, pending=None, lease_until=None, attempts=0, retry_at=None)

    def release(self, file_id: UUID, retry_at: datetime | None) -> None:
        self._update_file(file_id, lease_until=None, retry_at=retry_at)

    def requeue_download(self, file_id: UUID) -> None:
        self._update_file(file_id, pending=SyncPendingAction.DOWNLOAD, lease_until=None, retry_at=None)

    def _update_file(self, file_id: UUID, **values) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(sa.update(SyncFile).where(col(SyncFile.id) == file_id).values(**values))
            session.commit()

    def remove_file(self, file_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(sa.delete(SyncFile).where(col(SyncFile.id) == file_id))
            session.commit()

    def record_activity(self, folder: SyncAgentFolder, kind: SyncActivityKind, path: str, now: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.add(
                SyncActivity(
                    organization_id=folder.organization_id,
                    agent_id=folder.agent_id,
                    folder_id=folder.id,
                    kind=kind,
                    path=path,
                    occurred_at=now,
                )
            )
            session.commit()

    @staticmethod
    def _file_at(folder_id: UUID, path: str):
        return select(SyncFile).where(
            col(SyncFile.folder_id) == folder_id, sa.func.lower(col(SyncFile.path)) == path.lower()
        )

    def record_activity_once(
        self, folder: SyncAgentFolder, kind: SyncActivityKind, path: str, detail: str, now: datetime
    ) -> None:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(SyncActivity.id).where(
                    col(SyncActivity.folder_id) == folder.id,
                    col(SyncActivity.kind) == kind,
                    col(SyncActivity.path) == path,
                    col(SyncActivity.detail) == detail,
                )
            ).first()
            if existing is not None:
                return
            session.add(
                SyncActivity(
                    organization_id=folder.organization_id,
                    agent_id=folder.agent_id,
                    folder_id=folder.id,
                    kind=kind,
                    path=path,
                    detail=detail,
                    occurred_at=now,
                )
            )
            session.commit()

    def live_agent_names(self, organization_id: UUID) -> list[tuple[UUID, str]]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(Agent.id, Agent.name)
                .where(col(Agent.organization_id) == organization_id, col(Agent.deleted_at).is_(None))
                .order_by(col(Agent.created_at), col(Agent.id))
            )
            return [(agent_id, name) for agent_id, name in rows]

    def folders(self, connection_id: UUID) -> list[SyncAgentFolder]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.connection_id) == connection_id))
            )

    def reserve_folder(
        self, connection: SyncProviderConnection, agent_id: UUID, folder_name: str
    ) -> SyncAgentFolder | None:
        folder = SyncAgentFolder(
            organization_id=connection.organization_id,
            connection_id=connection.id,
            agent_id=agent_id,
            folder_name=folder_name,
            status=SyncFolderStatus.ACTIVE,
        )
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                session.add(folder)
                session.commit()
                return folder
        except IntegrityError:
            return None

    def record_folder(self, folder_id: UUID, *, item_id: str, web_url: str | None, path: str | None) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(SyncAgentFolder)
                .where(col(SyncAgentFolder.id) == folder_id)
                .values(folder_item_id=item_id, folder_web_url=web_url, folder_path=path)
            )
            session.commit()

    def rename_folder(self, folder_id: UUID, folder_name: str) -> bool:
        try:
            with Session(self.delegate.engine) as session:
                session.exec(
                    sa.update(SyncAgentFolder)
                    .where(col(SyncAgentFolder.id) == folder_id)
                    .values(folder_name=folder_name)
                )
                session.commit()
                return True
        except IntegrityError:
            return False

    def stop_folders(self, folder_ids: list[UUID]) -> None:
        if not folder_ids:
            return
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(SyncAgentFolder)
                .where(col(SyncAgentFolder.id).in_(folder_ids))
                .values(status=SyncFolderStatus.STOPPED)
            )
            session.commit()
