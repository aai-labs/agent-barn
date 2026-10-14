from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.onedrive_sync.models import OneDriveSyncConnection, OneDriveSyncStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

OPEN_CONNECTION_INDEX = "uq_onedrive_sync_connection_open"


class OneDriveSyncConnectionConflict(RuntimeError):
    pass


@inject
@singleton
@dataclass
class OneDriveSyncRepository:
    delegate: PostgresRepositoryDelegate

    def get_open(self, organization_id: UUID) -> OneDriveSyncConnection | None:
        with Session(self.delegate.engine) as session:
            return session.exec(self._open(organization_id)).first()

    def create_pending(
        self,
        organization_id: UUID,
        *,
        tenant_id: str,
        connected_by_user_id: UUID,
        pending_access_token: str,
        pending_expires_at: datetime,
    ) -> OneDriveSyncConnection:
        """A new pending connection, replacing any pending one in the same transaction.
        Refused while the Organization has an active connection."""
        connection = OneDriveSyncConnection(
            organization_id=organization_id,
            status=OneDriveSyncStatus.PENDING,
            tenant_id=tenant_id,
            connected_by_user_id=connected_by_user_id,
            pending_access_token=pending_access_token,
            pending_expires_at=pending_expires_at,
        )
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                session.exec(
                    sa.delete(OneDriveSyncConnection).where(
                        col(OneDriveSyncConnection.organization_id) == organization_id,
                        col(OneDriveSyncConnection.status) == OneDriveSyncStatus.PENDING,
                    )
                )
                session.add(connection)
                session.commit()
                return connection
        except IntegrityError as exc:
            if OPEN_CONNECTION_INDEX in str(exc):
                raise OneDriveSyncConnectionConflict("This Organization is already connected to OneDrive") from exc
            raise

    def activate(
        self,
        connection_id: UUID,
        *,
        site_id: str,
        site_name: str,
        site_url: str,
        folder_item_id: str,
        folder_web_url: str,
        permission_id: str,
    ) -> OneDriveSyncConnection | None:
        """Record the granted site and folder and drop the delegated token. None unless pending."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = self._locked(session, connection_id, OneDriveSyncStatus.PENDING)
            if connection is None:
                return None
            connection.status = OneDriveSyncStatus.ACTIVE
            connection.site_id = site_id
            connection.site_name = site_name
            connection.site_url = site_url
            connection.folder_item_id = folder_item_id
            connection.folder_web_url = folder_web_url
            connection.permission_id = permission_id
            connection.pending_access_token = None
            connection.pending_expires_at = None
            connection.connected_at = datetime.now(UTC)
            session.add(connection)
            session.commit()
            return connection

    def mark_disconnected(self, connection_id: UUID) -> OneDriveSyncConnection | None:
        """Close an active connection. None unless active."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = self._locked(session, connection_id, OneDriveSyncStatus.ACTIVE)
            if connection is None:
                return None
            connection.status = OneDriveSyncStatus.DISCONNECTED
            connection.disconnected_at = datetime.now(UTC)
            session.add(connection)
            session.commit()
            return connection

    def delete_pending(self, organization_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            result = session.exec(
                sa.delete(OneDriveSyncConnection).where(
                    col(OneDriveSyncConnection.organization_id) == organization_id,
                    col(OneDriveSyncConnection.status) == OneDriveSyncStatus.PENDING,
                )
            )
            session.commit()
            return result.rowcount > 0

    @staticmethod
    def _open(organization_id: UUID):
        return select(OneDriveSyncConnection).where(
            col(OneDriveSyncConnection.organization_id) == organization_id,
            col(OneDriveSyncConnection.status) != OneDriveSyncStatus.DISCONNECTED,
        )

    @staticmethod
    def _locked(session: Session, connection_id: UUID, status: OneDriveSyncStatus) -> OneDriveSyncConnection | None:
        return session.exec(
            select(OneDriveSyncConnection)
            .where(
                col(OneDriveSyncConnection.id) == connection_id,
                col(OneDriveSyncConnection.status) == status,
            )
            .with_for_update()
        ).first()
