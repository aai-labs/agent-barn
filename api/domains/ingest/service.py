import secrets
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import get_config
from api.core.metrics import TOOL_CALLS
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.ingest.models import IngestBatchRequest
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.crypto import decrypt_token


@inject
@singleton
@dataclass
class IngestService:
    agent_repository: AgentRepository
    tool_call_repository: ToolCallRepository

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
