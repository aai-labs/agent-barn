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
from api.domains.file_sync.models import SyncAgentFolder, SyncFolderStatus
from api.domains.sync_provider.models import SyncProviderConnection, SyncProviderStatus
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
