import logging
import secrets
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import get_config
from api.core.metrics import TOOL_CALLS
from api.domains.agents.models import Agent, AgentPlatform
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.models import AgentChatMessage
from api.domains.conversations.repository import ConversationRepository
from api.domains.ingest.models import IngestBatchRequest
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class IngestService:
    agent_repository: AgentRepository
    conversation_repository: ConversationRepository
    tool_call_repository: ToolCallRepository

    def authenticate(self, agent_id: UUID, provided_key: str) -> Agent:
        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None:
            raise PermissionError("agent not found")

        if not agent.ingest_key_encrypted:
            raise PermissionError("agent has no ingest key")

        config = get_config()
        stored_key = decrypt_token(
            agent.ingest_key_encrypted, config.agent_token_encryption_key
        )

        if not secrets.compare_digest(stored_key, provided_key):
            raise PermissionError("invalid ingest key")

        return agent

    def process(self, agent: Agent, batch: IngestBatchRequest) -> None:
        if batch.messages:
            self._process_messages(agent, batch)
        if batch.tool_calls or batch.tool_results:
            self._process_tool_calls(agent, batch)

    def _process_messages(self, agent: Agent, batch: IngestBatchRequest) -> None:
        user_map, channel_map = self._platform_maps(agent)

        messages = []
        for event in batch.messages:
            sender_name = event.sender_name
            if not sender_name and event.sender_id:
                sender_name = user_map.get(event.sender_id)

            channel_name = event.channel_name
            if not channel_name and event.channel_id:
                raw_id = event.channel_id
                if raw_id.startswith("USER:"):
                    channel_name = user_map.get(raw_id[5:])
                elif raw_id.startswith("CHANNEL:"):
                    channel_name = channel_map.get(raw_id[8:])
                else:
                    channel_name = channel_map.get(raw_id)

            messages.append(
                AgentChatMessage(
                    agent_id=agent.id,
                    openclaw_msg_id=event.msg_id,
                    session_key=event.session_key,
                    channel_id=event.channel_id,
                    thread_id=event.thread_id,
                    direction=event.direction,
                    conversation_type=event.conversation_type,
                    sender_id=event.sender_id,
                    sender_name=sender_name,
                    channel_name=channel_name,
                    content=event.content,
                    occurred_at=event.occurred_at,
                )
            )
        self.conversation_repository.upsert_messages(messages)

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

    def _platform_maps(self, agent: Agent) -> tuple[dict[str, str], dict[str, str]]:
        config = get_config()
        if not config.agent_token_encryption_key:
            return {}, {}
        if agent.platform == AgentPlatform.TEAMS:
            return {}, {}
        try:
            slack_config = self.agent_repository.get_slack_config(agent.id)
            if not slack_config:
                return {}, {}
            bot_token = decrypt_token(
                slack_config.bot_token_encrypted,
                config.agent_token_encryption_key,
            )
            slack = SlackClient(bot_token)
            users = slack.list_users(include_bots=True, include_deleted=True)
            channels = slack.list_channels()
            user_map = {
                u["id"]: u["display_name"] or u["real_name"] or u["name"] or u["id"]
                for u in users
            }
            channel_map = {
                c["id"]: c["name"] for c in channels if c["id"] and c["name"]
            }
            return user_map, channel_map
        except Exception as e:
            logger.warning("Failed to fetch Slack maps for agent %s: %s", agent.id, e)
            return {}, {}
