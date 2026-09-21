from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.error_details import (
    BACKLOG_CAP_EXCEEDED_MESSAGE,
    LEASE_EXPIRED_MESSAGE,
    error_code_from_details,
)
from api.domains.communications.execution_policy import (
    ORDERING_KEY_METADATA,
    DeliveryLimits,
    conversation_ordering_key,
    kind_for_location,
    kinds_for_protocol,
    ordering_key_for,
    policy_for,
    run_capped_kinds,
    runtime_execution,
    session_key_for,
)
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    CommunicationCallRead,
    CommunicationCallResponseRead,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationErrorDetails,
    CommunicationJournalStage,
    CommunicationRunLoadRead,
    ConversationLocation,
    DeliveryKind,
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
from api.infrastructure.shared.models import PaginatedItems, Pagination


class CommunicationDeliveryRetryError(RuntimeError):
    pass


class CommunicationDeliveryCancelledError(RuntimeError):
    pass


_BLOCKING_OUTBOUND_STATUSES = (
    CommunicationDeliveryStatus.PENDING,
    CommunicationDeliveryStatus.PROCESSING,
    CommunicationDeliveryStatus.DEAD_LETTERED,
)

# Why a delivery was dead-lettered without ever running.
BACKLOG_CAP_ERROR_CODE = "BACKLOG_CAP_EXCEEDED"


@inject
@singleton
@dataclass
class CommunicationDeliveryRepository:
    delegate: PostgresRepositoryDelegate
    config: Config
    operations: CommunicationOperationalRepository | None = None

    def _resolve_limits(self, override: DeliveryLimits | None) -> DeliveryLimits:
        """The limits in force: config unless a caller passes its own, which tests do."""
        return override if override is not None else DeliveryLimits.from_config(self.config)

    def accept_inbound(
        self,
        *,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
        limits: DeliveryLimits | None = None,
    ) -> AcceptedCommunicationRead:
        now = datetime.now(UTC)
        kind = kind_for_location(envelope.location)
        policy = policy_for(kind)
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

            # An event has nobody waiting on it, so it waits for the agent to start instead of
            # being dropped. Chat is dropped, as before.
            delivery_status = (
                CommunicationDeliveryStatus.PENDING
                if agent.status == AgentStatus.RUNNING or policy.queue_while_stopped
                else CommunicationDeliveryStatus.UNAVAILABLE
            )
            delivery = CommunicationDelivery(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection_id,
                message_id=message_id,
                direction=CommunicationDirection.INBOUND,
                status=delivery_status,
                kind=kind,
                session_key=session_key_for(connection_id, envelope),
                idempotency_key=envelope.provider_message_id,
                ordering_key=ordering_key_for(connection_id, envelope),
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
            # A queued event makes room for itself: past the cap the oldest waiting one is dropped.
            shed = (
                self._shed_backlog(session, connection_id, cap=self._resolve_limits(limits).backlog_cap, now=now)
                if policy.queue_while_stopped
                else []
            )
            session.commit()
            session.refresh(delivery)
            for dropped in shed:
                self._record_completion_metric(dropped)
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
        limits: DeliveryLimits | None = None,
        reclaim_expired: bool = True,
        runtime_protocol_version: int = 1,
        excluded_platform_keys: frozenset[str] = frozenset(),
    ) -> RuntimeDeliveryRead | None:
        limits = self._resolve_limits(limits)
        if reclaim_expired:
            self.reclaim_expired_inbound(
                agent_id=agent_id,
                limits=limits,
                excluded_platform_keys=excluded_platform_keys,
            )
        now = datetime.now(UTC)
        active_ordering = aliased(CommunicationDelivery)
        with Session(self.delegate.engine) as session:
            # Withhold kinds this pod's protocol version cannot execute; they stay PENDING.
            claimable = kinds_for_protocol(runtime_protocol_version)
            # At the in-flight cap the capped kinds are skipped as well. Chat is never counted, so an
            # event burst cannot hold up a reply. Skipped rows stay PENDING with no attempt spent.
            capped = claimable & run_capped_kinds()
            if capped and (
                self._capped_inbound_count(
                    session, agent_id, CommunicationDeliveryStatus.PROCESSING, excluded_platform_keys
                )
                >= limits.max_in_flight_runs
            ):
                claimable -= capped
            if not claimable:
                return None
            query = select(CommunicationDelivery).where(
                col(CommunicationDelivery.agent_id) == agent_id,
                col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PENDING,
                col(CommunicationDelivery.available_at) <= now,
                col(CommunicationDelivery.kind).in_(claimable),
                # An in-flight delivery holds its ordering key so a thread
                # never runs two turns at once -- unless its run is parked
                # awaiting a human answer, which can only arrive as the
                # next message on this very thread. Claiming that answer is
                # what unblocks the run, so it must not be blocked by it.
                ~sa.exists().where(
                    col(active_ordering.ordering_key) == col(CommunicationDelivery.ordering_key),
                    col(active_ordering.status) == CommunicationDeliveryStatus.PROCESSING,
                    col(active_ordering.awaiting_input).is_(False),
                ),
            )
            if excluded_platform_keys:
                query = query.join(
                    CommunicationConnection,
                    col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
                ).where(col(CommunicationConnection.platform_key).not_in(excluded_platform_keys))
            query = (
                query.order_by(
                    col(CommunicationDelivery.available_at).asc(),
                    col(CommunicationDelivery.created_at).asc(),
                    col(CommunicationDelivery.id).asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            delivery = session.exec(query).one_or_none()
            if delivery is None:
                session.commit()
                return None
            delivery.status = CommunicationDeliveryStatus.PROCESSING
            delivery.claimed_at = now
            delivery.lease_expires_at = now + timedelta(seconds=lease_seconds)
            # A freshly claimed delivery is running, not parked: it re-blocks
            # its ordering key until it completes or reports otherwise.
            delivery.awaiting_input = False
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
            return self._runtime_delivery(delivery)

    def _shed_backlog(
        self,
        session: Session,
        connection_id: UUID,
        *,
        cap: int,
        now: datetime,
    ) -> list[CommunicationDelivery]:
        """Dead-letter the oldest waiting deliveries beyond `cap`, so a backlog cannot grow without bound.

        A row a claim is holding is skipped and left for the next admission to shed.
        """
        waiting = (
            col(CommunicationDelivery.connection_id) == connection_id,
            col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
            col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PENDING,
        )
        count = session.exec(select(sa.func.count()).select_from(CommunicationDelivery).where(*waiting)).one()
        excess = count - cap
        if excess <= 0:
            return []
        oldest = list(
            session.exec(
                select(CommunicationDelivery)
                .where(*waiting)
                .order_by(col(CommunicationDelivery.created_at).asc(), col(CommunicationDelivery.id).asc())
                .limit(excess)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for delivery in oldest:
            delivery.status = CommunicationDeliveryStatus.DEAD_LETTERED
            delivery.completed_at = now
            delivery.last_error_code = BACKLOG_CAP_ERROR_CODE
            delivery.last_error_message = BACKLOG_CAP_EXCEEDED_MESSAGE
            session.add(delivery)
            self._stage_dead_lettered(session, delivery, now=now)
        return oldest

    @staticmethod
    def _capped_inbound_count(
        session: Session,
        agent_id: UUID,
        status: CommunicationDeliveryStatus,
        excluded_platform_keys: frozenset[str],
    ) -> int:
        """Inbound deliveries in one status, of the kinds the in-flight cap governs."""
        query = (
            select(sa.func.count())
            .select_from(CommunicationDelivery)
            .where(
                col(CommunicationDelivery.agent_id) == agent_id,
                col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                col(CommunicationDelivery.status) == status,
                col(CommunicationDelivery.kind).in_(run_capped_kinds()),
            )
        )
        if excluded_platform_keys:
            query = query.join(
                CommunicationConnection,
                col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
            ).where(col(CommunicationConnection.platform_key).not_in(excluded_platform_keys))
        return session.exec(query).one()

    def run_load(
        self,
        agent_id: UUID,
        *,
        excluded_platform_keys: frozenset[str] = frozenset(),
        limits: DeliveryLimits | None = None,
    ) -> CommunicationRunLoadRead:
        """How busy an Agent is with event runs, next to the cap that holds the rest back."""
        limits = self._resolve_limits(limits)
        with Session(self.delegate.engine) as session:
            return CommunicationRunLoadRead(
                in_flight=self._capped_inbound_count(
                    session, agent_id, CommunicationDeliveryStatus.PROCESSING, excluded_platform_keys
                ),
                max_in_flight=limits.max_in_flight_runs,
                queued=self._capped_inbound_count(
                    session, agent_id, CommunicationDeliveryStatus.PENDING, excluded_platform_keys
                ),
            )

    def find_active_inbound_delivery(
        self,
        *,
        connection_id: UUID,
        ordering_key: str,
    ) -> UUID | None:
        """Return the most recent still-in-flight inbound delivery for a thread.

        Used to resolve "the turn currently generating a reply" for a stop
        request, which only ever has the thread identity to go on.
        """
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(CommunicationDelivery.id)
                .where(
                    col(CommunicationDelivery.connection_id) == connection_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.ordering_key) == ordering_key,
                    col(CommunicationDelivery.status).in_(
                        (CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING)
                    ),
                )
                .order_by(
                    sa.case(
                        (col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING, 0),
                        else_=1,
                    ),
                    col(CommunicationDelivery.created_at).desc(),
                )
                .limit(1)
            ).one_or_none()

    def request_cancel(self, delivery_id: UUID, *, agent_id: UUID) -> CommunicationDeliveryStatus | None:
        """Mark an inbound delivery for cancellation.

        A delivery still PENDING (not yet claimed by the Runtime) is
        cancelled immediately — there is nothing in flight to interrupt. A
        PROCESSING delivery is only flagged; the caller pushes the actual
        interrupt to the Runtime pod (see
        CommunicationsGatewayService.request_cancel_delivery), and this flag
        makes that delivery's eventual completion terminal instead of
        retried (see `_apply_completion`) even if the push never lands.

        Returns the delivery's resulting status, or None if there was
        nothing left to cancel.
        """
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.status).in_(
                        (CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING)
                    ),
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return None
            delivery.cancel_requested_at = now
            if delivery.status == CommunicationDeliveryStatus.PENDING:
                delivery.status = CommunicationDeliveryStatus.CANCELLED
                delivery.completed_at = now
                delivery.last_error_code = "CANCELLED"
                delivery.last_error_message = "Cancelled by user"
            session.add(delivery)
            session.commit()
            return delivery.status

    def reclaim_expired_inbound(
        self,
        *,
        agent_id: UUID,
        limits: DeliveryLimits | None = None,
        excluded_platform_keys: frozenset[str] = frozenset(),
    ) -> list[RuntimeDeliveryRead]:
        """Reclaim stale runtime leases and return newly terminal deliveries."""
        limits = self._resolve_limits(limits)
        now = datetime.now(UTC)
        dead_lettered: list[RuntimeDeliveryRead] = []
        reclaimed: list[CommunicationDelivery] = []
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            query = select(CommunicationDelivery).where(
                col(CommunicationDelivery.agent_id) == agent_id,
                col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                col(CommunicationDelivery.lease_expires_at) < now,
            )
            if excluded_platform_keys:
                query = query.join(
                    CommunicationConnection,
                    col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
                ).where(col(CommunicationConnection.platform_key).not_in(excluded_platform_keys))
            expired = session.exec(query.with_for_update(skip_locked=True)).all()
            for stale in expired:
                self._apply_completion(
                    stale,
                    succeeded=False,
                    now=now,
                    # Nothing was reported, so this is inferred, not a reported failure.
                    max_attempts=self._max_attempts(stale, limits, reported=False),
                    error_code="LEASE_EXPIRED",
                    error_message=LEASE_EXPIRED_MESSAGE,
                    error_details=None,
                )
                session.add(stale)
                self._stage_completion_journal(session, stale, now=now)
                reclaimed.append(stale)
                if stale.status == CommunicationDeliveryStatus.DEAD_LETTERED:
                    dead_lettered.append(self._runtime_delivery(stale))
            session.commit()
        for stale in reclaimed:
            self._record_completion_metric(stale)
        return dead_lettered

    def renew_runtime_delivery_lease(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
        lease_seconds: int = 120,
        awaiting_input: bool = False,
    ) -> bool:
        """Extend a live runtime claim without allowing an expired claim to revive.

        The runtime reports whether this claim's run is parked awaiting a human
        answer on every heartbeat, so the flag re-converges even if a single
        transition call is lost.
        """
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                    col(CommunicationDelivery.lease_expires_at) > now,
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return False
            delivery.lease_expires_at = now + timedelta(seconds=lease_seconds)
            delivery.awaiting_input = awaiting_input
            session.add(delivery)
            session.commit()
            return True

    def release_runtime_delivery(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
        limits: DeliveryLimits | None = None,
        retry_after_seconds: int = 5,
    ) -> bool:
        """Put a claimed delivery back on the queue because its work never started.

        The attempt spent claiming it is given back, so a busy Agent does not use up the
        delivery's attempts. A delivery cancelled in the meantime ends as cancelled, and one
        whose earlier attempts already used the budget fails visibly rather than requeue.
        """
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
            # A release means nothing ran, which is no more a reported failure than a lease running out.
            max_attempts = self._max_attempts(delivery, self._resolve_limits(limits), reported=False)
            if delivery.cancel_requested_at is not None:
                self._apply_completion(
                    delivery,
                    succeeded=False,
                    now=now,
                    max_attempts=max_attempts,
                    error_code=None,
                    error_message=None,
                    error_details=None,
                )
            elif delivery.attempt_count >= max_attempts:
                self._apply_completion(
                    delivery,
                    succeeded=False,
                    now=now,
                    max_attempts=max_attempts,
                    error_code="RELEASE_LIMIT",
                    error_message="The Agent was busy on this delivery's last attempt",
                    error_details=None,
                )
            else:
                delivery.status = CommunicationDeliveryStatus.PENDING
                delivery.attempt_count = max(0, delivery.attempt_count - 1)
                delivery.available_at = now + timedelta(seconds=retry_after_seconds)
                delivery.claimed_at = None
                delivery.lease_expires_at = None
                delivery.awaiting_input = False
            session.add(delivery)
            if self.operations is not None:
                self.operations.stage_journal(
                    session=session,
                    organization_id=delivery.organization_id,
                    agent_id=delivery.agent_id,
                    connection_id=delivery.connection_id,
                    delivery_id=delivery.id,
                    stage=CommunicationJournalStage.RETRY_REQUESTED,
                    attempt_number=delivery.attempt_count,
                )
            session.commit()
            return True

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
            if source.cancel_requested_at is not None or source.status == CommunicationDeliveryStatus.CANCELLED:
                raise CommunicationDeliveryCancelledError("Source Communication Delivery was cancelled")
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
                approval=reply.approval,
            )
            message = AgentChatMessage(
                agent_id=agent_id,
                connection_id=source.connection_id,
                openclaw_msg_id=f"outbound:{reply.idempotency_key}",
                # Not source.ordering_key: for an event that is the caller's concurrency key.
                session_key=conversation_ordering_key(source.connection_id, inbound.location),
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
                # A reply carries the contract of what it answers.
                kind=source.kind,
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

    def list_calls(self, connection_id: UUID, *, pagination: Pagination) -> PaginatedItems[CommunicationCallRead]:
        """One page of a Connection's inbound requests, newest first, each with the replies
        the Agent sent for it.

        A reply is linked to its request only by `source_delivery_id` inside the outbound
        envelope; the chat transcript's session_key groups by location, not by exchange. An
        Agent may reply more than once, so `responses` is a list.
        """
        with Session(self.delegate.engine) as session:
            base_predicates = (
                col(CommunicationDelivery.connection_id) == connection_id,
                col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
            )
            total = session.exec(
                select(sa.func.count()).select_from(CommunicationDelivery).where(*base_predicates)
            ).one()
            inbound_rows = list(
                session.exec(
                    select(CommunicationDelivery)
                    .where(*base_predicates)
                    .order_by(col(CommunicationDelivery.created_at).desc(), col(CommunicationDelivery.id).desc())
                    .offset((pagination.page - 1) * pagination.size)
                    .limit(pagination.size)
                ).all()
            )
            responses_by_source: dict[UUID, list[CommunicationDelivery]] = defaultdict(list)
            if inbound_rows:
                inbound_ids = {str(row.id) for row in inbound_rows}
                outbound_rows = session.exec(
                    select(CommunicationDelivery).where(
                        col(CommunicationDelivery.connection_id) == connection_id,
                        col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                        col(CommunicationDelivery.envelope).op("->>")("source_delivery_id").in_(inbound_ids),
                    )
                ).all()
                for outbound in outbound_rows:
                    source_id = outbound.envelope.get("source_delivery_id")
                    if source_id is not None:
                        responses_by_source[UUID(source_id)].append(outbound)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[self._call_read(row, responses_by_source.get(row.id, [])) for row in inbound_rows],
        )

    @staticmethod
    def _call_read(delivery: CommunicationDelivery, responses: list[CommunicationDelivery]) -> CommunicationCallRead:
        envelope = delivery.envelope
        metadata = envelope.get("provider_metadata") or {}
        return CommunicationCallRead(
            delivery_id=delivery.id,
            event_id=delivery.idempotency_key,
            occurred_at=delivery.created_at,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            ordering_key=metadata.get(ORDERING_KEY_METADATA),
            prompt=envelope.get("text") or "",
            completed_at=delivery.completed_at,
            last_error_code=delivery.last_error_code,
            last_error_message=delivery.last_error_message,
            responses=[
                CommunicationCallResponseRead(
                    text=response.envelope.get("text") or "",
                    status=response.status,
                    occurred_at=response.created_at,
                )
                for response in sorted(responses, key=lambda item: item.created_at)
            ],
        )

    def claim_next_outbound(
        self,
        *,
        lease_seconds: int = 120,
        native_platform_keys: frozenset[str] = frozenset(),
    ) -> CommunicationDelivery | None:
        now = datetime.now(UTC)
        earlier_outbound = aliased(CommunicationDelivery)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            reclaim = sa.update(CommunicationDelivery).where(
                col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND,
                col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                col(CommunicationDelivery.lease_expires_at) < now,
            )
            if native_platform_keys:
                native_connection_ids = select(CommunicationConnection.id).where(
                    col(CommunicationConnection.platform_key).in_(native_platform_keys)
                )
                reclaim = reclaim.where(col(CommunicationDelivery.connection_id).not_in(native_connection_ids))
            session.exec(
                reclaim.values(status=CommunicationDeliveryStatus.PENDING, claimed_at=None, lease_expires_at=None)
            )
            query = (
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
            )
            if native_platform_keys:
                query = query.where(col(CommunicationConnection.platform_key).not_in(native_platform_keys))
            delivery = session.exec(
                query.order_by(
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
            return self._runtime_delivery(delivery)

    @staticmethod
    def select_inbound(source_id: UUID, agent_id: UUID) -> Any:
        """The one way to address an Agent's inbound delivery by id."""
        return select(CommunicationDelivery).where(
            col(CommunicationDelivery.id) == source_id,
            col(CommunicationDelivery.agent_id) == agent_id,
            col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
        )

    def source_is_cancelled(self, source_id: UUID, *, agent_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            source = session.exec(self.select_inbound(source_id, agent_id)).one_or_none()
            return (
                source is None
                or source.cancel_requested_at is not None
                or source.status == CommunicationDeliveryStatus.CANCELLED
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
        error_details: CommunicationErrorDetails | dict[str, Any] | None = None,
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
                error_details=error_details,
            )
            delivery.provider_message_id = provider_message_id
            session.add(delivery)
            self._stage_completion_journal(session, delivery, now=now, error_details=error_details)
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
        error_details: CommunicationErrorDetails | dict[str, Any] | None = None,
        limits: DeliveryLimits | None = None,
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
                # The pod told us the run failed, so this is a reported failure.
                max_attempts=self._max_attempts(delivery, self._resolve_limits(limits), reported=True),
                error_code=error_code,
                error_message=error_message,
                error_details=error_details,
            )
            session.add(delivery)
            self._stage_completion_journal(session, delivery, now=now, error_details=error_details)
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
        error_details: CommunicationErrorDetails | dict[str, Any] | None = None,
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
            error_details=error_details,
        )
        if delivery.status == CommunicationDeliveryStatus.DEAD_LETTERED:
            self._stage_dead_lettered(session, delivery, now=now, error_details=error_details)
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

    def _stage_dead_lettered(
        self,
        session: Session,
        delivery: CommunicationDelivery,
        *,
        now: datetime,
        error_details: CommunicationErrorDetails | dict[str, Any] | None = None,
    ) -> None:
        """Journal and announce a delivery that ended dead-lettered."""
        if self.operations is None:
            return
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
            error_details=error_details,
        )
        self._stage_delivery_event(
            session,
            delivery,
            event_name=COMMUNICATION_DELIVERY_DEAD_LETTERED,
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

    @staticmethod
    def _max_attempts(delivery: CommunicationDelivery, limits: DeliveryLimits, *, reported: bool) -> int:
        """How many claims this delivery gets. A failure the runtime reported and a lease that
        merely ran out are different: a run that failed will fail again, but a pod that died
        reported nothing and probably did nothing."""
        attempts = limits.attempts_for(delivery.kind)
        return attempts.after_failure if reported else attempts.after_lease_expiry

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
        error_details: CommunicationErrorDetails | dict[str, Any] | None,
    ) -> None:
        delivery.lease_expires_at = None
        safe_details = CommunicationOperationalRepository.safe_error_details(error_details)
        delivery.last_error_code = CommunicationOperationalRepository.safe_error_code(
            error_code
        ) or error_code_from_details(safe_details)
        delivery.last_error_message = CommunicationOperationalRepository.safe_error_summary(
            error_message,
            details=safe_details,
        )
        if delivery.cancel_requested_at is not None:
            # Cancellation wins even when a runtime that cannot hard-abort
            # reports success after the request. Retrying or publishing that
            # result would re-run work the user explicitly abandoned.
            delivery.status = CommunicationDeliveryStatus.CANCELLED
            delivery.completed_at = now
            delivery.last_error_code = delivery.last_error_code or "CANCELLED"
            delivery.last_error_message = delivery.last_error_message or "Cancelled by user"
        elif succeeded:
            delivery.status = CommunicationDeliveryStatus.SUCCEEDED
            delivery.completed_at = now
        elif safe_details is not None and not safe_details.retryable:
            # A normalized non-retryable provider response, such as HTTP 402,
            # is terminal even when the delivery still has retry attempts left.
            delivery.status = CommunicationDeliveryStatus.DEAD_LETTERED
            delivery.completed_at = now
        elif delivery.attempt_count >= max_attempts:
            delivery.status = CommunicationDeliveryStatus.DEAD_LETTERED
            delivery.completed_at = now
        else:
            delivery.status = CommunicationDeliveryStatus.PENDING
            delivery.available_at = now + timedelta(seconds=min(300, 2**delivery.attempt_count))
            delivery.claimed_at = None

    @staticmethod
    def _runtime_delivery(delivery: CommunicationDelivery) -> RuntimeDeliveryRead:
        """The wire view of a delivery. `session_key` is derived when the column is null,
        which is every row written before it existed."""
        envelope = NormalizedCommunicationEnvelope.model_validate(delivery.envelope)
        return RuntimeDeliveryRead(
            delivery_id=delivery.id,
            message_id=delivery.message_id,
            connection_id=delivery.connection_id,
            attempt_count=delivery.attempt_count,
            envelope=envelope,
            kind=DeliveryKind(delivery.kind),
            execution=runtime_execution(
                delivery.kind,
                delivery.session_key or session_key_for(delivery.connection_id, envelope),
            ),
        )

    @staticmethod
    def ordering_key_for_location(connection_id: UUID, location: ConversationLocation) -> str:
        """A conversation's ordering key; `execution_policy` owns the formula."""
        return conversation_ordering_key(connection_id, location)

    @staticmethod
    def _message_values(
        *,
        agent: Agent,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
        now: datetime,
    ) -> dict[str, Any]:
        # The transcript's grouping key, not the runtime session key: they share a formula
        # but are separate, and changing this one would give new rows a different shape.
        session_key = conversation_ordering_key(connection_id, envelope.location)
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
