import logging
import secrets
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from injector import inject, singleton
from sqlalchemy.exc import MultipleResultsFound

from api.core.config import get_config
from api.core.metrics import TOOL_CALLS
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import CommunicationJournalStage, ConnectionObservedStatus
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.conversations.models import AgentChatMessage
from api.domains.conversations.repository import ConversationRepository
from api.domains.ingest.models import IngestBatchRequest, IngestCommunicationEventBatch
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)

_HEALTH_BY_STAGE = {
    CommunicationJournalStage.CONNECTION_CONNECTING: ConnectionObservedStatus.CONNECTING,
    CommunicationJournalStage.CONNECTION_CONNECTED: ConnectionObservedStatus.CONNECTED,
    CommunicationJournalStage.CONNECTION_DEGRADED: ConnectionObservedStatus.DEGRADED,
    CommunicationJournalStage.CONNECTION_ERROR: ConnectionObservedStatus.ERROR,
}


@inject
@singleton
@dataclass
class IngestService:
    agent_repository: AgentRepository
    tool_call_repository: ToolCallRepository
    connection_repository: CommunicationConnectionRepository
    operational_repository: CommunicationOperationalRepository
    conversation_repository: ConversationRepository

    def authenticate(self, agent_id: UUID, provided_key: str) -> Agent:
        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None:
            raise PermissionError("agent not found")

        if not agent.ingest_key_encrypted:
            raise PermissionError("agent has no ingest key")

        config = get_config()
        stored_key = decrypt_token(agent.ingest_key_encrypted, config.agent_token_encryption_key)

        if not secrets.compare_digest(stored_key, provided_key):
            raise PermissionError("invalid ingest key")

        return agent

    def process(self, agent: Agent, batch: IngestBatchRequest) -> None:
        if batch.tool_calls or batch.tool_results:
            self._process_tool_calls(agent, batch)

    def record_communication_events(self, agent: Agent, batch: IngestCommunicationEventBatch) -> None:
        """Append native gateway stages to the Connection Journal.

        A native Connection is identified by its platform, so an Agent with
        several active Connections on one platform cannot be attributed and its
        events are dropped. Unknown stages (e.g. approval observations) are
        dropped until the Journal models them.
        """
        connections: dict[str, UUID | None] = {}
        for event in batch.events:
            try:
                stage = CommunicationJournalStage(event.stage)
            except ValueError:
                continue
            if event.platform not in connections:
                connections[event.platform] = self._native_connection_id(agent.id, event.platform)
            connection_id = connections[event.platform]
            if connection_id is None:
                continue
            if status := _HEALTH_BY_STAGE.get(stage):
                # Journals the transition itself, and keeps the Connection's
                # observed status current now that no supervisor session does.
                self.connection_repository.record_health(connection_id, status, error_code=event.error_code)
                continue
            # ponytail: one transaction per event; batch into one session if ingest volume shows up.
            self.operational_repository.record_journal(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection_id,
                stage=stage,
                # Deterministic, so every stage of one inbound message shares a Delivery timeline.
                delivery_id=uuid5(NAMESPACE_URL, f"{connection_id}:{event.correlation_id}")
                if event.correlation_id
                else None,
                occurred_at=event.occurred_at,
                error_code=event.error_code,
            )
        self._record_native_transcripts(agent, batch)

    def _record_native_transcripts(self, agent: Agent, batch: IngestCommunicationEventBatch) -> None:
        """Mirror observer-reported native messages into the dashboard transcript."""
        connection_ids: dict[str, UUID | None] = {}
        messages: list[AgentChatMessage] = []
        for transcript in batch.messages:
            if transcript.platform not in connection_ids:
                connection_ids[transcript.platform] = self._native_connection_id(agent.id, transcript.platform)
            connection_id = connection_ids[transcript.platform]
            if connection_id is None:
                continue
            messages.append(
                AgentChatMessage(
                    agent_id=agent.id,
                    connection_id=connection_id,
                    openclaw_msg_id=transcript.provider_message_id,
                    session_key=transcript.session_key,
                    channel_id=transcript.channel_id,
                    thread_id=transcript.thread_id,
                    direction=transcript.direction,
                    conversation_type=transcript.conversation_type,
                    sender_id=transcript.sender_id,
                    sender_name=transcript.sender_name,
                    channel_name=transcript.channel_name,
                    content=transcript.content,
                    occurred_at=transcript.occurred_at,
                )
            )
        self.conversation_repository.upsert_messages(messages)

    def _native_connection_id(self, agent_id: UUID, platform: str) -> UUID | None:
        try:
            connection = self.connection_repository.get_active_by_platform_key(agent_id, platform)
        except MultipleResultsFound:
            logger.warning("native %s events for agent %s match several Connections; dropped", platform, agent_id)
            return None
        return connection.id if connection else None

    def _process_tool_calls(self, agent: Agent, batch: IngestBatchRequest) -> None:
        with self.tool_call_repository.get_session() as session:
            for event in batch.tool_calls:
                self.tool_call_repository.upsert_pending(
                    session,
                    agent.organization_id,
                    agent.id,
                    event.session_id,
                    event.external_id,
                    event.tool_name,
                    event.arguments,
                    event.occurred_at,
                )
            for event in batch.tool_results:
                completed = self.tool_call_repository.complete(
                    session,
                    agent.id,
                    event.external_id,
                    event.result,
                    event.is_error,
                    event.completed_at,
                )
                if completed is not None:
                    TOOL_CALLS.labels(
                        tool_name=completed.tool_name,
                        status=completed.status.value.lower(),
                    ).inc()
            session.commit()
