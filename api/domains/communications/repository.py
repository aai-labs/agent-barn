from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    ConnectionObservedStatus,
)
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class CommunicationConnectionConflictError(RuntimeError):
    pass


@inject
@singleton
@dataclass
class CommunicationConnectionRepository:
    delegate: PostgresRepositoryDelegate

    def list_active_for_agent(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> list[CommunicationConnection]:
        with Session(self.delegate.engine) as session:
            query = (
                select(CommunicationConnection)
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    col(CommunicationConnection.agent_id) == agent_id,
                    col(CommunicationConnection.retired_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
                .order_by(
                    col(CommunicationConnection.display_name).asc(),
                    col(CommunicationConnection.id).asc(),
                )
            )
            return list(session.exec(query).all())

    def get_active_in_scope(
        self,
        connection_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> CommunicationConnection | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(CommunicationConnection)
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.agent_id) == agent_id,
                    col(CommunicationConnection.retired_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
            )
            return session.exec(query).one_or_none()

    def get_active(self, connection_id: UUID) -> CommunicationConnection | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(CommunicationConnection).where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.retired_at).is_(None),
                )
            ).one_or_none()

    def get_active_by_platform_key(self, agent_id: UUID, platform_key: str) -> CommunicationConnection | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(CommunicationConnection).where(
                    col(CommunicationConnection.agent_id) == agent_id,
                    col(CommunicationConnection.platform_key) == platform_key,
                    col(CommunicationConnection.retired_at).is_(None),
                )
            ).one_or_none()

    def list_enabled(self) -> list[CommunicationConnection]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(CommunicationConnection)
                    .where(
                        col(CommunicationConnection.enabled).is_(True),
                        col(CommunicationConnection.retired_at).is_(None),
                    )
                    .order_by(col(CommunicationConnection.id))
                ).all()
            )

    def record_health(
        self,
        connection_id: UUID,
        status: ConnectionObservedStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with Session(self.delegate.engine) as session:
            connection = session.get(CommunicationConnection, connection_id)
            if connection is None or connection.retired_at is not None:
                return
            connection.observed_status = status
            connection.last_health_at = datetime.now(UTC)
            connection.last_error_code = error_code
            connection.last_error_message = error_message[:500] if error_message else None
            session.add(connection)
            session.commit()

    def claim_ingress_lease(self, connection_id: UUID, owner: str, *, lease_seconds: int = 15) -> bool:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            claimed = session.exec(
                sa.update(CommunicationConnection)
                .where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                    sa.or_(
                        col(CommunicationConnection.ingress_lease_owner) == owner,
                        col(CommunicationConnection.ingress_lease_expires_at).is_(None),
                        col(CommunicationConnection.ingress_lease_expires_at) < now,
                    ),
                )
                .values(
                    ingress_lease_owner=owner,
                    ingress_lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
                .returning(sa.column("id"))
            ).first()
            session.commit()
            return claimed is not None

    def release_ingress_lease(self, connection_id: UUID, owner: str) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(CommunicationConnection)
                .where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.ingress_lease_owner) == owner,
                )
                .values(ingress_lease_owner=None, ingress_lease_expires_at=None)
            )
            session.commit()

    def create(self, connection: CommunicationConnection) -> CommunicationConnection:
        try:
            with Session(self.delegate.engine) as session:
                session.add(connection)
                session.commit()
                session.refresh(connection)
                return connection
        except IntegrityError as exc:
            raise CommunicationConnectionConflictError(self._conflict_detail(exc)) from exc

    def update(
        self,
        connection: CommunicationConnection,
        *,
        expected_revision: int,
    ) -> CommunicationConnection:
        try:
            with Session(self.delegate.engine) as session:
                persisted = session.exec(
                    select(CommunicationConnection).where(
                        col(CommunicationConnection.id) == connection.id,
                        col(CommunicationConnection.retired_at).is_(None),
                    )
                ).one_or_none()
                if persisted is None or persisted.revision != expected_revision:
                    raise CommunicationConnectionConflictError("Communication Connection changed; refresh and retry")
                values = connection.model_dump(
                    exclude={
                        "id",
                        "created_at",
                        "updated_at",
                        "revision",
                        "ingress_lease_owner",
                        "ingress_lease_expires_at",
                    },
                )
                for field, value in values.items():
                    setattr(persisted, field, value)
                persisted.revision += 1
                persisted.updated_at = datetime.now(UTC)
                session.add(persisted)
                session.commit()
                session.refresh(persisted)
                return persisted
        except IntegrityError as exc:
            raise CommunicationConnectionConflictError(self._conflict_detail(exc)) from exc

    def retire(
        self,
        connection_id: UUID,
        *,
        expected_revision: int,
    ) -> bool:
        with Session(self.delegate.engine) as session:
            connection = session.get(CommunicationConnection, connection_id)
            if connection is None or connection.retired_at is not None:
                return False
            if connection.revision != expected_revision:
                raise CommunicationConnectionConflictError("Communication Connection changed; refresh and retry")
            now = datetime.now(UTC)
            connection.enabled = False
            connection.observed_status = None
            connection.credentials_encrypted = ""
            connection.driver_key_encrypted = ""
            connection.credential_fingerprint = None
            connection.credential_scope_key = None
            connection.ingress_lease_owner = None
            connection.ingress_lease_expires_at = None
            connection.retired_at = now
            connection.updated_at = now
            connection.revision += 1
            session.add(connection)
            session.exec(
                sa.update(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.connection_id) == connection_id,
                    col(CommunicationDelivery.status).in_(
                        [CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING]
                    ),
                )
                .values(
                    status=CommunicationDeliveryStatus.CANCELLED,
                    completed_at=now,
                    lease_expires_at=None,
                    last_error_code="CONNECTION_RETIRED",
                    last_error_message="Communication Connection was retired",
                )
            )
            session.commit()
            return True

    @staticmethod
    def _conflict_detail(exc: IntegrityError) -> str:
        message = str(exc).lower()
        if "uq_communication_connection_active_name" in message:
            return "An active Communication Connection already uses this display name"
        if "uq_communication_connection_credential" in message:
            return "These platform credentials are already assigned within their allowed scope"
        return "Communication Connection conflicts with existing data"
