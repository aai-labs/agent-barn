from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.sync_provider.models import OPEN_CONNECTION_INDEX, SyncProviderConnection, SyncProviderStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class SyncProviderConnectionConflict(RuntimeError):
    pass


@inject
@singleton
@dataclass
class SyncProviderRepository:
    delegate: PostgresRepositoryDelegate

    def get_open(self, organization_id: UUID, provider_key: str) -> SyncProviderConnection | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                self._open(organization_id).where(col(SyncProviderConnection.provider_key) == provider_key)
            ).first()

    def list_open(self, organization_id: UUID) -> list[SyncProviderConnection]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(self._open(organization_id).order_by(col(SyncProviderConnection.provider_key))))

    def create_pending(
        self,
        organization_id: UUID,
        provider_key: str,
        *,
        schema_version: int,
        account_id: str,
        connected_by_user_id: UUID,
        credentials_encrypted: str,
        pending_expires_at: datetime,
    ) -> SyncProviderConnection:
        """A new pending connection, replacing this provider's pending one in the same transaction.
        Refused while the open-connection index already holds a row for the Organization."""
        connection = SyncProviderConnection(
            organization_id=organization_id,
            provider_key=provider_key,
            schema_version=schema_version,
            status=SyncProviderStatus.PENDING,
            account_id=account_id,
            connected_by_user_id=connected_by_user_id,
            credentials_encrypted=credentials_encrypted,
            pending_expires_at=pending_expires_at,
        )
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                session.exec(self._delete_pending(organization_id, provider_key))
                session.add(connection)
                session.commit()
                return connection
        except IntegrityError as exc:
            if OPEN_CONNECTION_INDEX in str(exc):
                raise SyncProviderConnectionConflict("This Organization already has an open sync connection") from exc
            raise

    def activate(
        self,
        connection_id: UUID,
        *,
        location_id: str | None,
        location_name: str | None,
        location_url: str | None,
        folder_id: str,
        folder_web_url: str,
        provider_data: dict[str, str],
    ) -> SyncProviderConnection | None:
        """Record the location, folder and provider data and drop the delegated token. None unless pending."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = self._locked(session, connection_id, SyncProviderStatus.PENDING)
            if connection is None:
                return None
            connection.status = SyncProviderStatus.ACTIVE
            connection.location_id = location_id
            connection.location_name = location_name
            connection.location_url = location_url
            connection.folder_id = folder_id
            connection.folder_web_url = folder_web_url
            connection.provider_data = provider_data
            connection.credentials_encrypted = None
            connection.pending_expires_at = None
            connection.connected_at = datetime.now(UTC)
            session.add(connection)
            session.commit()
            return connection

    def mark_disconnected(self, connection_id: UUID) -> SyncProviderConnection | None:
        """Close an active connection. None unless active."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = self._locked(session, connection_id, SyncProviderStatus.ACTIVE)
            if connection is None:
                return None
            connection.status = SyncProviderStatus.DISCONNECTED
            connection.disconnected_at = datetime.now(UTC)
            session.add(connection)
            session.commit()
            return connection

    def delete_pending(self, organization_id: UUID, provider_key: str) -> bool:
        with Session(self.delegate.engine) as session:
            result = session.exec(self._delete_pending(organization_id, provider_key))
            session.commit()
            return result.rowcount > 0

    @staticmethod
    def _open(organization_id: UUID):
        return select(SyncProviderConnection).where(
            col(SyncProviderConnection.organization_id) == organization_id,
            col(SyncProviderConnection.status) != SyncProviderStatus.DISCONNECTED,
        )

    @staticmethod
    def _delete_pending(organization_id: UUID, provider_key: str):
        return sa.delete(SyncProviderConnection).where(
            col(SyncProviderConnection.organization_id) == organization_id,
            col(SyncProviderConnection.provider_key) == provider_key,
            col(SyncProviderConnection.status) == SyncProviderStatus.PENDING,
        )

    @staticmethod
    def _locked(session: Session, connection_id: UUID, status: SyncProviderStatus) -> SyncProviderConnection | None:
        return session.exec(
            select(SyncProviderConnection)
            .where(
                col(SyncProviderConnection.id) == connection_id,
                col(SyncProviderConnection.status) == status,
            )
            .with_for_update()
        ).first()
