from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.file_sync.models import SyncAgentFolder, SyncFolderStatus
from api.domains.sync_provider.models import SyncProviderConnection
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class FileSyncRepository:
    delegate: PostgresRepositoryDelegate

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
