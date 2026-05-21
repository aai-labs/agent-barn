import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationChannelRead,
    ConversationMessageRead,
    ConversationSessionRead,
    ConversationsRead,
)
from api.domains.conversations.parser import parse_sessions
from api.domains.conversations.repository import ConversationRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)

_SESSIONS_PATH = "/home/node/.openclaw/agents/main/sessions/sessions.json"
_SESSION_DIR = "/home/node/.openclaw/agents/main/sessions"


def _slack_session_uuids(sessions_json: str) -> list[str]:
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []
    uuids: list[str] = []
    for key, data in sessions.items():
        if not key.startswith("agent:main:slack:channel:"):
            continue
        uuid = (data or {}).get("sessionId")
        if uuid:
            uuids.append(uuid)
    return uuids


@inject
@singleton
@dataclass
class ConversationService:
    repository: ConversationRepository
    agent_repository: AgentRepository
    k8s: KubernetesClient
    config: Config

    def _safe_read_jsonl(self, pod_name: str, ns: str, session_uuid: str) -> str:
        try:
            return self.k8s.exec_command(
                pod_name, ns, ["cat", f"{_SESSION_DIR}/{session_uuid}.jsonl"]
            )
        except Exception as e:
            logger.warning("Failed to read JSONL for session %s: %s", session_uuid, e)
            return ""

    def sync(self, agent_id: UUID) -> None:
        ns = self.config.k8s_namespace
        deployment_name = f"agent-{agent_id}"
        pod_name = self.k8s.get_pod_name_for_deployment(deployment_name, ns)
        if not pod_name:
            logger.info(
                "No running pod for agent %s — skipping conversation sync", agent_id
            )
            return

        sessions_json = self.k8s.exec_command(pod_name, ns, ["cat", _SESSIONS_PATH])

        session_uuids = _slack_session_uuids(sessions_json)
        jsonl_cache: dict[str, str] = {}
        if session_uuids:
            with ThreadPoolExecutor(max_workers=min(8, len(session_uuids))) as pool:
                jsonl_cache = dict(
                    zip(
                        session_uuids,
                        pool.map(
                            lambda uuid: self._safe_read_jsonl(pod_name, ns, uuid),
                            session_uuids,
                        ),
                    )
                )

        def get_jsonl(session_uuid: str) -> str:
            return jsonl_cache.get(session_uuid, "")

        user_map: dict[str, str] = {}
        channel_map: dict[str, str] = {}
        agent = self.agent_repository.get_by_id(agent_id)
        if agent and self.config.agent_token_encryption_key:
            try:
                bot_token = decrypt_token(
                    agent.slack_bot_token_encrypted,
                    self.config.agent_token_encryption_key,
                )
                slack = SlackClient(bot_token)
                channel_map = slack.get_channel_map()
                user_map = slack.get_user_map()
                logger.info(
                    "Fetched %d channels and %d users from Slack for agent %s",
                    len(channel_map),
                    len(user_map),
                    agent_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to fetch Slack maps for agent %s: %s", agent_id, e
                )

        messages = parse_sessions(
            agent_id, sessions_json, get_jsonl, user_map, channel_map
        )
        self.repository.upsert_messages(messages)
        logger.info("Synced %d messages for agent %s", len(messages), agent_id)

    def get_conversations(self, agent_id: UUID, org_id: UUID) -> ConversationsRead:
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )
        if agent.status == AgentStatus.RUNNING:
            try:
                self.sync(agent_id)
            except Exception as e:
                logger.warning("Conversation sync failed for agent %s: %s", agent_id, e)

        messages: list[AgentChatMessage] = self.repository.find_by_agent(agent_id)
        return _build_response(messages)


def _build_response(messages: list[AgentChatMessage]) -> ConversationsRead:
    # channel_id → session_key → [messages]
    channel_sessions: dict[str, dict[str, list[AgentChatMessage]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # preserve session ordering: channel sessions (thread_id=None) before threads
    session_thread_id: dict[str, str | None] = {}
    # first known channel name per channel_id (from inbound messages)
    channel_names: dict[str, str] = {}

    for msg in messages:
        channel_sessions[msg.channel_id][msg.session_key].append(msg)
        session_thread_id[msg.session_key] = msg.thread_id
        if msg.channel_name and msg.channel_id not in channel_names:
            channel_names[msg.channel_id] = msg.channel_name

    channels: list[ConversationChannelRead] = []
    for channel_id, sessions_map in sorted(channel_sessions.items()):
        # Sort: channel-level session first, then threads by thread_id
        def session_sort_key(sk: str) -> tuple:
            tid = session_thread_id.get(sk)
            return (0 if tid is None else 1, tid or "")

        sessions: list[ConversationSessionRead] = []
        for session_key in sorted(sessions_map.keys(), key=session_sort_key):
            msgs = sessions_map[session_key]
            thread_id = session_thread_id.get(session_key)
            sessions.append(
                ConversationSessionRead(
                    session_key=session_key,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    messages=[ConversationMessageRead.model_validate(m) for m in msgs],
                )
            )
        channels.append(
            ConversationChannelRead(
                channel_id=channel_id,
                channel_name=channel_names.get(channel_id),
                sessions=sessions,
            )
        )

    return ConversationsRead(channels=channels)
