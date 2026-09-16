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
from api.domains.communications.error_details import error_code_from_details
from api.domains.communications.models import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_TOTAL_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    AcceptedCommunicationRead,
    CommunicationAttachment,
    CommunicationAttachmentContent,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationErrorDetails,
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


class CommunicationDeliveryCancelledError(RuntimeError):
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

    def store_attachment_content(
        self,
        *,
        agent_id: UUID,
        idempotency_key: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> CommunicationAttachment:
        """Store one runtime-produced file idempotently within its Agent boundary."""
        if not idempotency_key or len(idempotency_key) > 512:
            raise ValueError("Attachment idempotency key must be between 1 and 512 characters")
        filename = filename.strip()
        if not filename or len(filename) > 255:
            raise ValueError("Attachment filename must be between 1 and 255 characters")
        media_type = media_type.strip()
        if not media_type or len(media_type) > 255:
            raise ValueError("Attachment media type must be between 1 and 255 characters")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte limit")

        with Session(self.delegate.engine) as session:
            session.exec(
                sa.delete(CommunicationAttachmentContent).where(
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.outbound_delivery_id).is_(None),
                    col(CommunicationAttachmentContent.created_at) < datetime.now(UTC) - timedelta(days=1),
                )
            )
            statement = (
                insert(CommunicationAttachmentContent)
                .values(
                    agent_id=agent_id,
                    idempotency_key=idempotency_key,
                    filename=filename,
                    media_type=media_type,
                    size_bytes=len(content),
                    content=content,
                )
                .on_conflict_do_nothing(index_elements=["agent_id", "idempotency_key"])
            )
            session.exec(statement)
            stored = session.exec(
                select(CommunicationAttachmentContent).where(
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.idempotency_key) == idempotency_key,
                )
            ).one()
            session.commit()
            return self._attachment_metadata(stored)

    def attachment_contents(
        self,
        *,
        agent_id: UUID,
        attachments: list[CommunicationAttachment],
    ) -> list[CommunicationAttachmentContent]:
        """Resolve outbound attachment references in request order and tenant scope."""
        if not attachments:
            return []
        try:
            attachment_ids = [UUID(item.id) for item in attachments]
        except ValueError as exc:
            raise LookupError("Attachment content not found") from exc
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            stored = session.exec(
                select(CommunicationAttachmentContent).where(
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.id).in_(attachment_ids),
                )
            ).all()
            by_id = {item.id: item for item in stored}
            try:
                return [by_id[attachment_id] for attachment_id in attachment_ids]
            except KeyError as exc:
                raise LookupError("Attachment content not found") from exc

    def retain_attachments_for_provider_consent(
        self, *, agent_id: UUID, attachments: list[CommunicationAttachment]
    ) -> None:
        """Keep files after the consent-card delivery until Teams accepts or declines them."""
        if not attachments:
            return
        attachment_ids = [UUID(item.id) for item in attachments]
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(CommunicationAttachmentContent)
                .where(
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.id).in_(attachment_ids),
                )
                .values(pending_provider_consent=True)
            )
            session.commit()

    def pending_attachment_content(
        self, *, agent_id: UUID, connection_id: UUID, attachment_id: UUID
    ) -> CommunicationAttachmentContent | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            return session.exec(
                select(CommunicationAttachmentContent)
                .join(
                    CommunicationDelivery,
                    col(CommunicationDelivery.id) == col(CommunicationAttachmentContent.outbound_delivery_id),
                )
                .where(
                    col(CommunicationAttachmentContent.id) == attachment_id,
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.pending_provider_consent).is_(True),
                    col(CommunicationDelivery.connection_id) == connection_id,
                )
            ).one_or_none()

    def delete_attachment_content(self, *, agent_id: UUID, attachment_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.delete(CommunicationAttachmentContent).where(
                    col(CommunicationAttachmentContent.id) == attachment_id,
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                )
            )
            session.commit()

    def record_provider_attachment_id(
        self, *, agent_id: UUID, attachment_id: UUID, provider_attachment_id: str
    ) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(CommunicationAttachmentContent)
                .where(
                    col(CommunicationAttachmentContent.id) == attachment_id,
                    col(CommunicationAttachmentContent.agent_id) == agent_id,
                    col(CommunicationAttachmentContent.provider_attachment_id).is_(None),
                )
                .values(provider_attachment_id=provider_attachment_id)
            )
            session.commit()

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
        max_attempts: int = 5,
        reclaim_expired: bool = True,
    ) -> RuntimeDeliveryRead | None:
        if reclaim_expired:
            self.reclaim_expired_inbound(agent_id=agent_id, max_attempts=max_attempts)
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
            return RuntimeDeliveryRead(
                delivery_id=delivery.id,
                message_id=delivery.message_id,
                connection_id=delivery.connection_id,
                attempt_count=delivery.attempt_count,
                envelope=NormalizedCommunicationEnvelope.model_validate(delivery.envelope),
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
        max_attempts: int = 5,
    ) -> list[RuntimeDeliveryRead]:
        """Reclaim stale runtime leases and return newly terminal deliveries."""
        now = datetime.now(UTC)
        dead_lettered: list[RuntimeDeliveryRead] = []
        reclaimed: list[CommunicationDelivery] = []
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            expired = session.exec(
                select(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.agent_id) == agent_id,
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                    col(CommunicationDelivery.status) == CommunicationDeliveryStatus.PROCESSING,
                    col(CommunicationDelivery.lease_expires_at) < now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for stale in expired:
                self._apply_completion(
                    stale,
                    succeeded=False,
                    now=now,
                    max_attempts=max_attempts,
                    error_code="LEASE_EXPIRED",
                    error_message="Runtime did not complete this delivery before its claim lease expired",
                    error_details=None,
                )
                session.add(stale)
                self._stage_completion_journal(session, stale, now=now)
                reclaimed.append(stale)
                if stale.status == CommunicationDeliveryStatus.DEAD_LETTERED:
                    dead_lettered.append(
                        RuntimeDeliveryRead(
                            delivery_id=stale.id,
                            message_id=stale.message_id,
                            connection_id=stale.connection_id,
                            attempt_count=stale.attempt_count,
                            envelope=NormalizedCommunicationEnvelope.model_validate(stale.envelope),
                        )
                    )
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

            if len(reply.attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
                raise ValueError(f"A reply can contain at most {MAX_ATTACHMENTS_PER_MESSAGE} attachments")
            stored_attachments = self._attachment_contents_in_session(
                session,
                agent_id=agent_id,
                attachments=reply.attachments,
            )
            if sum(item.size_bytes for item in stored_attachments) > MAX_ATTACHMENT_TOTAL_BYTES:
                raise ValueError(f"Reply attachments exceed the {MAX_ATTACHMENT_TOTAL_BYTES}-byte total limit")
            canonical_attachments = [self._attachment_metadata(item) for item in stored_attachments]
            inbound = NormalizedCommunicationEnvelope.model_validate(source.envelope)
            outbound = OutboundCommunicationEnvelope(
                source_delivery_id=source.id,
                location=inbound.location,
                text=reply.text,
                attachments=canonical_attachments,
                reply_to_provider_message_id=inbound.provider_message_id,
                provider_metadata=inbound.provider_metadata,
                approval=reply.approval,
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
            session.flush()
            for item in stored_attachments:
                if item.outbound_delivery_id is not None:
                    raise LookupError("Attachment content is already assigned to another reply")
                item.outbound_delivery_id = delivery.id
                session.add(item)
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

    @staticmethod
    def _attachment_contents_in_session(
        session: Session,
        *,
        agent_id: UUID,
        attachments: list[CommunicationAttachment],
    ) -> list[CommunicationAttachmentContent]:
        if not attachments:
            return []
        try:
            attachment_ids = [UUID(item.id) for item in attachments]
        except ValueError as exc:
            raise LookupError("Attachment content not found") from exc
        stored = session.exec(
            select(CommunicationAttachmentContent)
            .where(
                col(CommunicationAttachmentContent.agent_id) == agent_id,
                col(CommunicationAttachmentContent.id).in_(attachment_ids),
            )
            .with_for_update()
        ).all()
        by_id = {item.id: item for item in stored}
        try:
            return [by_id[attachment_id] for attachment_id in attachment_ids]
        except KeyError as exc:
            raise LookupError("Attachment content not found") from exc

    @staticmethod
    def _attachment_metadata(stored: CommunicationAttachmentContent) -> CommunicationAttachment:
        return CommunicationAttachment(
            id=str(stored.id),
            media_type=stored.media_type,
            filename=stored.filename,
            size_bytes=stored.size_bytes,
        )

    def attachment_metadata(self, stored: CommunicationAttachmentContent) -> CommunicationAttachment:
        """Return the runtime-safe metadata for stored attachment bytes."""
        return self._attachment_metadata(stored)

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
            if delivery.status == CommunicationDeliveryStatus.SUCCEEDED:
                self._delete_delivered_attachment_contents(session, delivery)
            self._stage_completion_journal(session, delivery, now=now, error_details=error_details)
            session.commit()
            self._record_completion_metric(delivery)
            return True

    @staticmethod
    def _delete_delivered_attachment_contents(session: Session, delivery: CommunicationDelivery) -> None:
        outbound = OutboundCommunicationEnvelope.model_validate(delivery.envelope)
        try:
            attachment_ids = [UUID(item.id) for item in outbound.attachments]
        except ValueError:
            return
        if attachment_ids:
            session.exec(
                sa.delete(CommunicationAttachmentContent).where(
                    col(CommunicationAttachmentContent.agent_id) == delivery.agent_id,
                    col(CommunicationAttachmentContent.id).in_(attachment_ids),
                    col(CommunicationAttachmentContent.pending_provider_consent).is_(False),
                )
            )

    def complete_runtime_delivery(
        self,
        delivery_id: UUID,
        *,
        agent_id: UUID,
        succeeded: bool,
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
    def ordering_key_for_location(connection_id: UUID, location: ConversationLocation) -> str:
        thread = location.thread_id or "root"
        return f"{connection_id}:{location.id}:{thread}"

    @staticmethod
    def ordering_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
        return CommunicationDeliveryRepository.ordering_key_for_location(connection_id, envelope.location)

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
