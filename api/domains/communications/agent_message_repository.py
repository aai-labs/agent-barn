"""Atomic initiated submission identity, canonical history, and journal persistence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    AgentMessageRead,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationJournalStage,
    OutboundCommunicationEnvelope,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class AgentMessageConflictError(RuntimeError):
    pass


@inject
@singleton
@dataclass
class AgentMessageRepository:
    delegate: PostgresRepositoryDelegate
    operations: CommunicationOperationalRepository

    @staticmethod
    def _existing(session: Session, agent_id: UUID, key: str, digest: str) -> AgentMessageRead | None:
        delivery = session.exec(
            select(CommunicationDelivery).where(
                col(CommunicationDelivery.agent_id) == agent_id,
                col(CommunicationDelivery.submission_key) == key,
            )
        ).one_or_none()
        if delivery is None:
            return None
        if delivery.request_digest != digest:
            raise AgentMessageConflictError("Submission key was already used for a different request")
        return AgentMessageRead(delivery_id=delivery.id, status=delivery.status)

    def existing(self, agent_id: UUID, key: str, digest: str) -> AgentMessageRead | None:
        with Session(self.delegate.engine) as session:
            return self._existing(session, agent_id, key, digest)

    @staticmethod
    def _require_execution(
        session: Session, agent_id: UUID, source_id: UUID, attempt: int, *, lock: bool = False
    ) -> CommunicationDelivery:
        query = CommunicationDeliveryRepository.select_inbound(source_id, agent_id)
        if lock:
            query = query.with_for_update()
        source = session.exec(query).one_or_none()
        if (
            source is None
            or source.status != CommunicationDeliveryStatus.PROCESSING
            or source.cancel_requested_at is not None
            or source.attempt_count != attempt
            or source.lease_expires_at is None
            or source.lease_expires_at <= datetime.now(UTC)
        ):
            raise PermissionError("An active, uncancelled inbound execution is required")
        return source

    def origin_conversation_type(self, agent_id: UUID, connection_id: UUID, channel_id: str) -> ConversationType | None:
        """The conversation type we recorded for this channel, or None if we never saw it.

        A runtime-supplied origin is untrusted input. Requiring canonical history proves
        the Agent really was in that conversation rather than taking the claim on faith,
        and tells the plugin whether to resolve a channel or a DM.
        """
        with Session(self.delegate.engine) as session:
            conversation_type = session.exec(
                select(AgentChatMessage.conversation_type)
                .where(
                    col(AgentChatMessage.agent_id) == agent_id,
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                )
                .limit(1)
            ).first()
            return ConversationType(conversation_type) if conversation_type is not None else None

    def execution_connection_id(self, agent_id: UUID, source_id: UUID, attempt: int) -> UUID:
        """The Connection an active inbound execution arrived on, for routing its sends."""
        with Session(self.delegate.engine) as session:
            return self._require_execution(session, agent_id, source_id, attempt).connection_id

    def accept(
        self,
        *,
        agent: Agent,
        connection: CommunicationConnection,
        key: str,
        digest: str,
        envelope: OutboundCommunicationEnvelope,
        attempt: int | None,
    ) -> AgentMessageRead:
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            # Serialize logical submissions at the Agent, independently of Connection.
            current_agent = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == agent.id,
                    col(Agent.organization_id) == agent.organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if current_agent is None or current_agent.status != AgentStatus.RUNNING:
                raise AgentMessageConflictError("Agent is not running")
            existing = self._existing(session, agent.id, key, digest)
            if existing is not None:
                return existing
            current = session.exec(
                select(CommunicationConnection)
                .where(
                    col(CommunicationConnection.id) == connection.id,
                    col(CommunicationConnection.agent_id) == agent.id,
                    col(CommunicationConnection.organization_id) == agent.organization_id,
                    col(CommunicationConnection.retired_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if current is None or not current.enabled:
                raise AgentMessageConflictError("Communication Connection is unavailable")
            if current.revision != connection.revision:
                raise AgentMessageConflictError("Connection configuration changed; retry the submission")
            if envelope.source_delivery_id is not None:
                self._require_execution(session, agent.id, envelope.source_delivery_id, attempt or 0, lock=True)
            location = envelope.location
            ordering = CommunicationDeliveryRepository.ordering_key_for_location(connection.id, location)
            message = AgentChatMessage(
                agent_id=agent.id,
                connection_id=connection.id,
                openclaw_msg_id=f"initiated:{key}",
                session_key=ordering,
                channel_id=location.id,
                thread_id=location.thread_id,
                channel_name=location.display_name,
                direction=MessageDirection.OUTBOUND,
                conversation_type=ConversationType(location.type),
                content=envelope.text,
                occurred_at=now,
            )
            session.add(message)
            session.flush()
            delivery = CommunicationDelivery(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection.id,
                message_id=message.id,
                direction=CommunicationDirection.OUTBOUND,
                idempotency_key=f"initiated:{key}",
                submission_key=key,
                request_digest=digest,
                ordering_key=ordering,
                available_at=now,
                envelope=envelope.model_dump(mode="json"),
            )
            session.add(delivery)
            self.operations.stage_journal(
                session=session,
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection.id,
                delivery_id=delivery.id,
                stage=CommunicationJournalStage.INITIATED_QUEUED,
                attempt_number=1,
            )
            session.commit()
            return AgentMessageRead(delivery_id=delivery.id, status=delivery.status)
