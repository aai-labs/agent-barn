from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationJournalStage,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    RuntimeDeliveryRead,
    RuntimeReplyCreate,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationType,
    MessageDirection,
)
from api.domains.events.catalog import (
    COMMUNICATION_DELIVERY_DEAD_LETTERED,
    COMMUNICATION_DELIVERY_RECOVERED,
    COMMUNICATION_DELIVERY_RETRY_REQUESTED,
)
from api.domains.events.models import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class CommunicationDeliveryRetryError(RuntimeError):
    pass


_BLOCKING_OUTBOUND_STATUSES = (
    CommunicationDeliveryStatus.PENDING,
    CommunicationDeliveryStatus.PROCESSING,
    CommunicationDeliveryStatus.DEAD_LETTERED,
)


@inject
@singleton
@dataclass
class CommunicationDeliveryRepository:
    delegate: PostgresRepositoryDelegate
    operations: CommunicationOperationalRepository | None = None

    def accept_inbound(
        self,
        *,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
    ) -> AcceptedCommunicationRead:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            connection = session.exec(
                select(CommunicationConnection)
                .where(col(CommunicationConnection.id) == connection_id)
                .with_for_update()
            ).one_or_none()
            if connection is None or connection.retired_at is not None or not connection.enabled:
                raise LookupError("Communication Connection is unavailable")
            agent = session.get(Agent, connection.agent_id)
            if agent is None or agent.deleted_at is not None:
                raise LookupError("Agent is unavailable")

            message_values = self._message_values(
                agent=agent,
                connection_id=connection_id,
                envelope=envelope,
                now=now,
            )
            message_insert = (
                insert(AgentChatMessage)
                .values(message_values)
                .on_conflict_do_nothing(
                    index_elements=["connection_id", "openclaw_msg_id"],
                    index_where=sa.text("connection_id IS NOT NULL"),
                )
                .returning(cast(Any, AgentChatMessage.id))
            )
            inserted_message = session.exec(message_insert).one_or_none()
            duplicate = inserted_message is None
            if inserted_message is None:
                message_id = self._backfill_message_names(session, connection_id, envelope)
            else:
                message_id = cast(UUID, inserted_message[0])

            existing = session.exec(
                select(CommunicationDelivery).where(
                    col(CommunicationDelivery.connection_id) == connection_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.idempotency_key) == envelope.provider_message_id,
                )
            ).one_or_none()
            if existing is not None:
                self._backfill_delivery_names(existing, envelope)
                session.commit()
                return AcceptedCommunicationRead(
                    message_id=message_id,
                    delivery_id=existing.id,
                    status=existing.status,
                    duplicate=True,
                )

            delivery_status = (
                CommunicationDeliveryStatus.PENDING
                if agent.status == AgentStatus.RUNNING
                else CommunicationDeliveryStatus.UNAVAILABLE
            )
            delivery = CommunicationDelivery(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection_id,
                message_id=message_id,
                direction=CommunicationDirection.INBOUND,
                status=delivery_status,
                idempotency_key=envelope.provider_message_id,
                ordering_key=self.ordering_key(connection_id, envelope),
                available_at=now,
                completed_at=now if delivery_status == CommunicationDeliveryStatus.UNAVAILABLE else None,
                last_error_code="AGENT_STOPPED" if delivery_status == CommunicationDeliveryStatus.UNAVAILABLE else None,
                last_error_message="Agent was not running when the message arrived"
                if delivery_status == CommunicationDeliveryStatus.UNAVAILABLE
                else None,
                envelope=envelope.model_dump(mode="json"),
            )
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.QUEUED,
                    attempt_number=1 if delivery.status == CommunicationDeliveryStatus.PENDING else 0,
                    error_code=delivery.last_error_code,
                    error_summary=delivery.last_error_message,
                )
            session.commit()
            session.refresh(delivery)
            return AcceptedCommunicationRead(
                message_id=message_id,
                delivery_id=delivery.id,
                status=delivery.status,
                duplicate=duplicate,
            )

    def claim_next_inbound(
        self,
        *,
        agent_id: UUID,
        lease_seconds: int = 120,
    ) -> RuntimeDeliveryRead | None:
        now = datetime.now(UTC)
        active_ordering = aliased(CommunicationDelivery)
        with Session(self.delegate.engine) as session:
            query = (
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PENDING,
                    col(CommunicationDelivery.available_at) <= now,
                    ~sa.exists().where(
                        col(active_ordering.ordering_key) == col(CommunicationDelivery.ordering_key),
                        col(active_ordering.status) == CommunicationDeliveryStatus.PROCESSING,
                    ),
                )
                .order_by(
                    col(CommunicationDelivery.available_at).asc(),
                    col(CommunicationDelivery.created_at).asc(),
                    col(CommunicationDelivery.id).asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            delivery = session.exec(query).one_or_none()
            if delivery is None:
                return None
            delivery.status = CommunicationDeliveryStatus.PROCESSING
            delivery.claimed_at = now
            delivery.lease_expires_at = now + timedelta(seconds=lease_seconds)
            delivery.attempt_count += 1
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.AGENT_CLAIMED,
                    attempt_number=delivery.attempt_count,
                )
            session.commit()
            session.refresh(delivery)
            return RuntimeDeliveryRead(
                delivery_id=delivery.id,
                message_id=delivery.message_id,
                connection_id=delivery.connection_id,
                attempt_count=delivery.attempt_count,
                envelope=NormalizedCommunicationEnvelope.model_validate(delivery.envelope),
            )

    def thread_has_agent_state(
        self,
        *,
        connection_id: UUID,
        location: ConversationLocation,
    ) -> bool:
        """Return whether this Connection has persisted state for a thread.

        A thread becomes Agent-owned only after an inbound or outbound
        Communication message has been persisted for this exact Connection and
        provider location. This deliberately avoids process-local ownership
        caches, which would diverge across Communications replicas.
        """
        if not location.thread_id:
            return False
        with Session(self.delegate.engine) as session:
            message = session.exec(
                select(AgentChatMessage.id)
                .where(
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == location.id,
                    col(AgentChatMessage.thread_id) == location.thread_id,
                )
                .limit(1)
            ).one_or_none()
            return message is not None

    def enqueue_runtime_reply(
        self,
        *,
        agent_id: UUID,
        source_delivery_id: UUID,
        reply: RuntimeReplyCreate,
    ) -> UUID:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            source = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.id) == source_delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                )
                .with_for_update()
            ).one_or_none()
            if source is None:
                raise LookupError("Source Communication Delivery not found")
            existing = session.exec(
                select(CommunicationDelivery).where(
                    col(CommunicationDelivery.connection_id) == source.connection_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                    col(CommunicationDelivery.idempotency_key) == reply.idempotency_key,
                )
            ).one_or_none()
            if existing is not None:
                return existing.id

            inbound = NormalizedCommunicationEnvelope.model_validate(source.envelope)
            outbound = OutboundCommunicationEnvelope(
                source_delivery_id=source.id,
                location=inbound.location,
                text=reply.text,
                attachments=reply.attachments,
                reply_to_provider_message_id=inbound.provider_message_id,
                provider_metadata=inbound.provider_metadata,
            )
            message = AgentChatMessage(
                agent_id=agent_id,
                connection_id=source.connection_id,
                openclaw_msg_id=f"outbound:{reply.idempotency_key}",
                session_key=source.ordering_key,
                channel_id=inbound.location.id,
                thread_id=inbound.location.thread_id,
                channel_name=inbound.location.display_name,
                direction=MessageDirection.OUTBOUND,
                conversation_type=ConversationType(inbound.location.type),
                content=reply.text,
                occurred_at=now,
            )
            session.add(message)
            session.flush()
            delivery = CommunicationDelivery(
                organization_id=source.organization_id,
                agent_id=agent_id,
                connection_id=source.connection_id,
                message_id=message.id,
                direction=CommunicationDirection.OUTBOUND,
                status=CommunicationDeliveryStatus.PENDING,
                idempotency_key=reply.idempotency_key,
                ordering_key=source.ordering_key,
                available_at=now,
                envelope=outbound.model_dump(mode="json"),
            )
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.REPLY_QUEUED,
                    attempt_number=1,
                )
            session.commit()
            session.refresh(delivery)
            return delivery.id

    def claim_next_outbound(self, *, lease_seconds: int = 120) -> CommunicationDelivery | None:
        now = datetime.now(UTC)
        earlier_outbound = aliased(CommunicationDelivery)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.exec(
                sa.update(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                    col(CommunicationDelivery.lease_expires_at) < now,
                )
                .values(status=CommunicationDeliveryStatus.PENDING, claimed_at=None, lease_expires_at=None)
            )
            delivery = session.exec(
                select(CommunicationDelivery)
                .join(
                    CommunicationConnection,
                    col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
                )
                .where(
                    col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PENDING,
                    col(CommunicationDelivery.available_at) <= now,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                    # A conversation is a single ordered stream. A later
                    # reply cannot overtake an earlier pending, in-flight, or
                    # dead-lettered delivery; retrying that earlier row is the
                    # explicit operator decision that releases it.
                    ~sa.exists().where(
                        col(earlier_outbound.connection_id) == col(CommunicationDelivery.connection_id),
                        col(earlier_outbound.direction) == CommunicationDirection.OUTBOUND,
                        col(earlier_outbound.ordering_key) == col(CommunicationDelivery.ordering_key),
                        sa.or_(
                            col(earlier_outbound.created_at) < col(CommunicationDelivery.created_at),
                            sa.and_(
                                col(earlier_outbound.created_at) == col(CommunicationDelivery.created_at),
                                col(earlier_outbound.id) < col(CommunicationDelivery.id),
                            ),
                        ),
                        col(earlier_outbound.status).in_(_BLOCKING_OUTBOUND_STATUSES),
                    ),
                )
                .order_by(
                    col(CommunicationDelivery.available_at).asc(),
                    col(CommunicationDelivery.created_at).asc(),
                    col(CommunicationDelivery.id).asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            ).one_or_none()
            if delivery is None:
                session.commit()
                return None
            delivery.status = CommunicationDeliveryStatus.PROCESSING
            delivery.claimed_at = now
            delivery.lease_expires_at = now + timedelta(seconds=lease_seconds)
            delivery.attempt_count += 1
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.PROVIDER_DELIVERY_ATTEMPTED,
                    attempt_number=delivery.attempt_count,
                )
            session.commit()
            return delivery

    def get_inbound_runtime_delivery(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
    ) -> RuntimeDeliveryRead | None:
        """Load a claimed inbound delivery for lifecycle feedback context."""
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery).where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                )
            ).one_or_none()
            if delivery is None:
                return None
            return RuntimeDeliveryRead(
                delivery_id=delivery.id,
                message_id=delivery.message_id,
                connection_id=delivery.connection_id,
                attempt_count=delivery.attempt_count,
                envelope=NormalizedCommunicationEnvelope.model_validate(delivery.envelope),
            )

    def delivery_status(
        self,
        delivery_id: UUID,
        *,
        direction: CommunicationDirection,
    ) -> CommunicationDeliveryStatus | None:
        with Session(self.delegate.engine) as session:
            status = session.exec(
                select(CommunicationDelivery.status).where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.direction) == direction,
                )
            ).one_or_none()
            return CommunicationDeliveryStatus(status) if status is not None else None

    def complete_outbound(
        self,
        delivery_id: UUID,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        max_attempts: int = 5,
    ) -> bool:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return False
            self._apply_completion(
                delivery,
                succeeded=provider_message_id is not None,
                now=now,
                max_attempts=max_attempts,
                error_code=error_code,
                error_message=error_message,
            )
            delivery.provider_message_id = provider_message_id
            session.add(delivery)
            self._stage_completion_journal(session, delivery, now=now)
            session.commit()
            self._record_completion_metric(delivery)
            return True

    def complete_runtime_delivery(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
        succeeded: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        max_attempts: int = 5,
    ) -> bool:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return False
            self._apply_completion(
                delivery,
                succeeded=succeeded,
                now=now,
                max_attempts=max_attempts,
                error_code=error_code,
                error_message=error_message,
            )
            session.add(delivery)
            self._stage_completion_journal(session, delivery, now=now)
            session.commit()
            self._record_completion_metric(delivery)
            return True

    def retry_dead_lettered(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
        connection_id: UUID,
        actor: ActorIdentity,
    ) -> CommunicationDelivery:
        """Requeue one terminal outbound row without creating a new message.

        The delivery's idempotency key, message row, and provider envelope are
        preserved. Resetting the in-row attempt counter opens a fresh bounded
        retry window; the journal retains the complete prior attempt history.
        """
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            delivery = session.exec(
                select(CommunicationDelivery)
                .join(
                    CommunicationConnection,
                    col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
                )
                .where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.connection_id) == connection_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.DEAD_LETTERED,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                raise CommunicationDeliveryRetryError("Only an active dead-lettered outbound delivery can be retried")
            connection = session.get(CommunicationConnection, delivery.connection_id)
            if connection is None:
                raise CommunicationDeliveryRetryError("Communication Connection is unavailable")
            delivery.status = CommunicationDeliveryStatus.PENDING
            delivery.attempt_count = 0
            delivery.available_at = now
            delivery.claimed_at = None
            delivery.lease_expires_at = None
            delivery.completed_at = None
            delivery.provider_message_id = None
            delivery.last_error_code = None
            delivery.last_error_message = None
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.RETRY_REQUESTED,
                    attempt_number=1,
                )
                self.operations.stage_event(
                    session=session,
                    event_name=COMMUNICATION_DELIVERY_RETRY_REQUESTED,
                    organization_id=delivery.organization_id,
                    actor=actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT,
                        id=delivery.agent_id,
                        organization_id=delivery.organization_id,
                    ),
                    payload={
                        "organization_id": delivery.organization_id,
                        "agent_id": delivery.agent_id,
                        "connection_id": delivery.connection_id,
                        "delivery_id": delivery.id,
                        "direction": self._enum_value(delivery.direction),
                        "attempt_number": 1,
                        "actor_display": self._actor_display(actor),
                        "subject_display": connection.display_name,
                    },
                    occurred_at=now,
                )
            session.commit()
            session.refresh(delivery)
            return delivery

    def _stage_completion_journal(
        self,
        session: Session,
        delivery: CommunicationDelivery,
        *,
        now: datetime,
    ) -> None:
        if self.operations is None:
            return
        if delivery.direction == CommunicationDirection.OUTBOUND:
            stage = (
                CommunicationJournalStage.PROVIDER_DELIVERED
                if delivery.status == CommunicationDeliveryStatus.SUCCEEDED
                else CommunicationJournalStage.PROVIDER_DELIVERY_ATTEMPTED
            )
        else:
            stage = CommunicationJournalStage.MODEL_COMPLETED
        self.operations.stage_journal(
            session=session,
            organization_id=delivery.organization_id,
            agent_id=delivery.agent_id,
            connection_id=delivery.connection_id,
            delivery_id=delivery.id,
            stage=stage,
            attempt_number=delivery.attempt_count,
            occurred_at=now,
            error_code=delivery.last_error_code,
            error_summary=delivery.last_error_message,
        )
        if delivery.status == CommunicationDeliveryStatus.DEAD_LETTERED:
            self.operations.stage_journal(
                session=session,
                organization_id=delivery.organization_id,
                agent_id=delivery.agent_id,
                connection_id=delivery.connection_id,
                delivery_id=delivery.id,
                stage=CommunicationJournalStage.DEAD_LETTERED,
                attempt_number=delivery.attempt_count,
                occurred_at=now,
                error_code=delivery.last_error_code,
                error_summary=delivery.last_error_message,
            )
            self._stage_delivery_event(
                session,
                delivery,
                event_name=COMMUNICATION_DELIVERY_DEAD_LETTERED,
                occurred_at=now,
            )
        elif delivery.status == CommunicationDeliveryStatus.SUCCEEDED and self.operations.has_stage(
            session,
            delivery_id=delivery.id,
            stage=CommunicationJournalStage.RETRY_REQUESTED,
        ):
            self.operations.stage_journal(
                session=session,
                organization_id=delivery.organization_id,
                agent_id=delivery.agent_id,
                connection_id=delivery.connection_id,
                delivery_id=delivery.id,
                stage=CommunicationJournalStage.RECOVERED,
                attempt_number=delivery.attempt_count,
                occurred_at=now,
            )
            self._stage_delivery_event(
                session,
                delivery,
                event_name=COMMUNICATION_DELIVERY_RECOVERED,
                occurred_at=now,
            )

    def _stage_delivery_event(
        self,
        session: Session,
        delivery: CommunicationDelivery,
        *,
        event_name: str,
        occurred_at: datetime,
    ) -> None:
        if self.operations is None:
            return
        connection = session.get(CommunicationConnection, delivery.connection_id)
        subject_display = connection.display_name if connection is not None else "Communication Connection"
        payload = {
            "organization_id": delivery.organization_id,
            "agent_id": delivery.agent_id,
            "connection_id": delivery.connection_id,
            "delivery_id": delivery.id,
            "direction": self._enum_value(delivery.direction),
            "attempt_number": delivery.attempt_count,
            "actor_display": "Communications Runtime",
            "subject_display": subject_display,
        }
        if event_name == COMMUNICATION_DELIVERY_DEAD_LETTERED:
            payload.update(
                {
                    "error_code": delivery.last_error_code,
                    "error_summary": delivery.last_error_message,
                }
            )
        self.operations.stage_event(
            session=session,
            event_name=event_name,
            organization_id=delivery.organization_id,
            actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="communications-runtime"),
            subject=SubjectIdentity(
                type=SubjectIdentityType.AGENT,
                id=delivery.agent_id,
                organization_id=delivery.organization_id,
            ),
            payload=payload,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _actor_display(actor: ActorIdentity) -> str:
        return "Communications Runtime" if actor.type == ActorIdentityType.SYSTEM else str(actor.id)

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _record_completion_metric(delivery: CommunicationDelivery) -> None:
        from api.domains.communications.metrics import record_delivery_outcome

        record_delivery_outcome(delivery)

    @classmethod
    def _apply_completion(
        cls,
        delivery: CommunicationDelivery,
        *,
        succeeded: bool,
        now: datetime,
        max_attempts: int,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        delivery.lease_expires_at = None
        delivery.last_error_code = CommunicationOperationalRepository.safe_error_code(error_code)
        delivery.last_error_message = CommunicationOperationalRepository.safe_error_summary(error_message)
        if succeeded:
            delivery.status = CommunicationDeliveryStatus.SUCCEEDED
            delivery.completed_at = now
        elif delivery.attempt_count >= max_attempts:
            delivery.status = CommunicationDeliveryStatus.DEAD_LETTERED
            delivery.completed_at = now
        else:
            delivery.status = CommunicationDeliveryStatus.PENDING
            delivery.available_at = now + timedelta(seconds=min(300, 2**delivery.attempt_count))
            delivery.claimed_at = None

    @staticmethod
    def ordering_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
        thread = envelope.location.thread_id or "root"
        return f"{connection_id}:{envelope.location.id}:{thread}"

    @staticmethod
    def _message_values(
        *,
        agent: Agent,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
        now: datetime,
    ) -> dict[str, Any]:
        session_key = CommunicationDeliveryRepository.ordering_key(connection_id, envelope)
        return {
            "id": uuid7(),
            "created_at": now,
            "updated_at": now,
            "agent_id": agent.id,
            "connection_id": connection_id,
            "openclaw_msg_id": envelope.provider_message_id,
            "session_key": session_key,
            "channel_id": envelope.location.id,
            "thread_id": envelope.location.thread_id,
            "direction": MessageDirection.INBOUND,
            "conversation_type": ConversationType(envelope.location.type),
            "sender_id": envelope.sender.id,
            "sender_name": envelope.sender.display_name,
            "channel_name": envelope.location.display_name,
            "content": envelope.text,
            "occurred_at": envelope.occurred_at,
        }

    @staticmethod
    def _backfill_message_names(
        session: Session,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
    ) -> UUID:
        """Backfill names on a duplicate delivery's existing message row.

        Runs only on the conflict path (a provider retry of an already-durable
        message), so a fresh insert's values are never touched here. COALESCE
        keeps any already-known name and only fills a column that is still
        NULL, so a retry can supply a name the first attempt lacked without
        ever clearing a name a prior attempt already resolved.
        """
        update = (
            sa.update(AgentChatMessage)
            .where(
                col(AgentChatMessage.connection_id) == connection_id,
                col(AgentChatMessage.openclaw_msg_id) == envelope.provider_message_id,
            )
            .values(
                sender_name=sa.func.coalesce(col(AgentChatMessage.sender_name), envelope.sender.display_name),
                channel_name=sa.func.coalesce(col(AgentChatMessage.channel_name), envelope.location.display_name),
            )
            .returning(cast(Any, AgentChatMessage.id))
        )
        return cast(UUID, session.exec(update).one()[0])

    @staticmethod
    def _backfill_delivery_names(
        delivery: CommunicationDelivery,
        envelope: NormalizedCommunicationEnvelope,
    ) -> None:
        """Backfill names in a duplicate delivery's runtime envelope.

        The canonical message row and the delivery envelope are both read by
        later consumers. Preserve any name already stored and only fill a
        missing display name from a provider retry.
        """
        stored = dict(delivery.envelope)
        sender = dict(stored.get("sender") or {})
        location = dict(stored.get("location") or {})
        if sender.get("display_name") is None and envelope.sender.display_name is not None:
            sender["display_name"] = envelope.sender.display_name
        if location.get("display_name") is None and envelope.location.display_name is not None:
            location["display_name"] = envelope.location.display_name
        stored["sender"] = sender
        stored["location"] = location
        delivery.envelope = stored
