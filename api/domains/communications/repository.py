from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.error_details import error_code_from_details
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationErrorDetails,
    CommunicationJournalStage,
    ConnectionObservedStatus,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.events.catalog import (
    COMMUNICATION_CONNECTION_HEALTH_CHANGED,
    COMMUNICATION_CONNECTION_RECONNECT_REQUESTED,
)
from api.domains.events.models import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class CommunicationConnectionConflictError(RuntimeError):
    pass


# Observed statuses that represent a stable failure. Repeated retries cycle
# ERROR -> CONNECTING -> ERROR without leaving the failure state; the health
# Domain Event fires only when that boundary is actually crossed (ticket
# AF-273: retries and intermediate timing belong in the journal and metrics).
_FAILURE_STATUSES = {ConnectionObservedStatus.DEGRADED, ConnectionObservedStatus.ERROR}


def _emits_health_event(previous: ConnectionObservedStatus | None, new: ConnectionObservedStatus) -> bool:
    """Debounce health events to entry/exit of a failure state."""
    if new in _FAILURE_STATUSES:
        return (
            previous is not None
            and previous not in _FAILURE_STATUSES
            and previous != ConnectionObservedStatus.CONNECTING
        )
    if new is ConnectionObservedStatus.CONNECTED:
        return previous is None or previous in _FAILURE_STATUSES
    return False


@inject
@singleton
@dataclass
class CommunicationConnectionRepository:
    delegate: PostgresRepositoryDelegate
    operations: CommunicationOperationalRepository | None = None

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
        error_details: CommunicationErrorDetails | dict[str, Any] | None = None,
    ) -> None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = session.get(CommunicationConnection, connection_id)
            if connection is None or connection.retired_at is not None:
                return
            previous_status = connection.observed_status
            safe_details = CommunicationOperationalRepository.safe_error_details(error_details)
            safe_code = CommunicationOperationalRepository.safe_error_code(error_code) or error_code_from_details(
                safe_details
            )
            safe_message = CommunicationOperationalRepository.safe_error_summary(error_message, details=safe_details)
            connection.observed_status = status
            connection.last_health_at = datetime.now(UTC)
            connection.last_error_code = safe_code
            connection.last_error_message = safe_message
            connection.last_error_details = (
                safe_details.model_dump(mode="json", exclude_none=True) if safe_details is not None else None
            )
            session.add(connection)
            if previous_status != status and self.operations is not None:
                stage_by_status = {
                    ConnectionObservedStatus.PENDING: CommunicationJournalStage.CONNECTION_CONNECTING,
                    ConnectionObservedStatus.CONNECTING: CommunicationJournalStage.CONNECTION_CONNECTING,
                    ConnectionObservedStatus.CONNECTED: CommunicationJournalStage.CONNECTION_CONNECTED,
                    ConnectionObservedStatus.DEGRADED: CommunicationJournalStage.CONNECTION_DEGRADED,
                    ConnectionObservedStatus.ERROR: CommunicationJournalStage.CONNECTION_ERROR,
                }
                self.operations.stage_journal(
                    session=session,
                    organization_id=connection.organization_id,
                    agent_id=connection.agent_id,
                    connection_id=connection.id,
                    stage=stage_by_status[status],
                    error_code=safe_code,
                    error_summary=safe_message,
                    error_details=safe_details,
                )
                if _emits_health_event(previous_status, status):
                    self.operations.stage_event(
                        session=session,
                        event_name=COMMUNICATION_CONNECTION_HEALTH_CHANGED,
                        organization_id=connection.organization_id,
                        actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="communications-supervisor"),
                        subject=SubjectIdentity(
                            type=SubjectIdentityType.AGENT,
                            id=connection.agent_id,
                            organization_id=connection.organization_id,
                        ),
                        payload={
                            "organization_id": connection.organization_id,
                            "agent_id": connection.agent_id,
                            "connection_id": connection.id,
                            "previous_status": self._status_value(previous_status),
                            "new_status": status.value,
                            "error_code": safe_code,
                            "error_summary": safe_message,
                            "error_details": safe_details.model_dump(mode="json", exclude_none=True)
                            if safe_details is not None
                            else None,
                            "actor_display": "Communications Supervisor",
                            "subject_display": connection.display_name,
                        },
                    )
            session.commit()

    def request_reconnect(
        self,
        connection_id: UUID,
        *,
        actor: ActorIdentity,
    ) -> CommunicationConnection | None:
        requested_at = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            connection = session.exec(
                select(CommunicationConnection)
                .where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.retired_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if connection is None:
                return None
            previous_status = connection.observed_status
            connection.revision += 1
            connection.updated_at = requested_at
            if connection.enabled:
                connection.observed_status = ConnectionObservedStatus.CONNECTING
                connection.last_health_at = requested_at
            connection.last_error_code = None
            connection.last_error_message = None
            connection.last_error_details = None
            session.add(connection)
            if self.operations is not None:
                if connection.enabled and previous_status != ConnectionObservedStatus.CONNECTING:
                    self.operations.stage_journal(
                        session=session,
                        organization_id=connection.organization_id,
                        agent_id=connection.agent_id,
                        connection_id=connection.id,
                        stage=CommunicationJournalStage.CONNECTION_CONNECTING,
                        occurred_at=requested_at,
                    )
                    self.operations.stage_event(
                        session=session,
                        event_name=COMMUNICATION_CONNECTION_HEALTH_CHANGED,
                        organization_id=connection.organization_id,
                        actor=actor,
                        subject=SubjectIdentity(
                            type=SubjectIdentityType.AGENT,
                            id=connection.agent_id,
                            organization_id=connection.organization_id,
                        ),
                        payload={
                            "organization_id": connection.organization_id,
                            "agent_id": connection.agent_id,
                            "connection_id": connection.id,
                            "previous_status": self._status_value(previous_status),
                            "new_status": ConnectionObservedStatus.CONNECTING.value,
                            "error_code": None,
                            "error_summary": None,
                            "actor_display": self._actor_display(actor),
                            "subject_display": connection.display_name,
                        },
                        occurred_at=requested_at,
                    )
                self.operations.stage_journal(
                    session=session,
                    organization_id=connection.organization_id,
                    agent_id=connection.agent_id,
                    connection_id=connection.id,
                    stage=CommunicationJournalStage.RECONNECT_REQUESTED,
                )
                self.operations.stage_event(
                    session=session,
                    event_name=COMMUNICATION_CONNECTION_RECONNECT_REQUESTED,
                    organization_id=connection.organization_id,
                    actor=actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT,
                        id=connection.agent_id,
                        organization_id=connection.organization_id,
                    ),
                    payload={
                        "organization_id": connection.organization_id,
                        "agent_id": connection.agent_id,
                        "connection_id": connection.id,
                        "actor_display": self._actor_display(actor),
                        "subject_display": connection.display_name,
                    },
                    occurred_at=requested_at,
                )
            session.commit()
            session.refresh(connection)
            from api.domains.communications.metrics import record_reconnect

            record_reconnect()
            return connection

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

    @staticmethod
    def _status_value(status: ConnectionObservedStatus | None) -> str | None:
        return status.value if status is not None else None

    @staticmethod
    def _actor_display(actor: ActorIdentity) -> str:
        if actor.type == ActorIdentityType.SYSTEM:
            return "Communications Supervisor"
        return str(actor.id)
