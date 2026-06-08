import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import AgentPlatform, AgentStatus, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.hermes_parser import (
    HERMES_SESSIONS_PATH,
    hermes_channel_sessions,
    hermes_distinct_conversations,
    parse_hermes_export,
)
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationChannelRead,
    ConversationMessageRead,
    ConversationThreadRead,
    ConversationThreadsPage,
    ConversationType,
    ConversationsCursor,
    ConversationsFilter,
)
from api.domains.conversations.parser import parse_sessions
from api.domains.conversations.repository import ConversationRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)

_SESSIONS_PATH = "/home/node/.openclaw/agents/main/sessions/sessions.json"
_SESSION_DIR = "/home/node/.openclaw/agents/main/sessions"
_PER_CHANNEL_SYNC_INTERVAL = timedelta(seconds=4)
_PLATFORM_MAPS_TTL = timedelta(seconds=60)
_STOP_SYNC_MAX_WORKERS = 4
_PER_CHANNEL_READ_MAX_WORKERS = 8
_FIRE_AND_FORGET_MAX_WORKERS = 4


_SESSION_PREFIXES = (
    "agent:main:slack:channel:",
    "agent:main:msteams:channel:",
    "agent:main:msteams:group:",
)


def _channel_sessions(
    sessions_json: str, target_channel_id: str | None
) -> list[tuple[str, str]]:
    """Returns [(session_key, session_uuid)] for platform sessions.

    If target_channel_id is provided, filters to only sessions matching it
    (case-insensitive on the channel_id).
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []
    target_upper = target_channel_id.upper() if target_channel_id else None
    out: list[tuple[str, str]] = []
    for key, data in sessions.items():
        if not any(key.startswith(p) for p in _SESSION_PREFIXES):
            continue
        data = data or {}
        if target_upper is not None:
            native = (data.get("origin") or {}).get("nativeChannelId") or data.get(
                "groupId"
            )
            if not native or native.upper() != target_upper:
                continue
        session_uuid = data.get("sessionId")
        if session_uuid:
            out.append((key, session_uuid))
    return out


def _distinct_pod_conversations(
    sessions_json: str,
) -> list[tuple[str, ConversationType, str | None]]:
    """Returns distinct (channel_id, conversation_type, display_name) triples.

    display_name is None for channels (resolved later via Slack API) and the
    sender name from origin.label / origin.sender for DMs.
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []
    seen: dict[str, tuple[ConversationType, str | None]] = {}
    for key, data in sessions.items():
        if not any(key.startswith(p) for p in _SESSION_PREFIXES):
            continue
        data = data or {}
        native = (data.get("origin") or {}).get("nativeChannelId") or data.get(
            "groupId"
        )
        if native:
            seen[native.upper()] = (ConversationType.CHANNEL, None)
    dm_data = sessions.get("agent:main:main") or {}
    origin = dm_data.get("origin") or {}
    if dm_data.get("chatType") == "direct" and origin.get("provider") == "slack":
        native = origin.get("nativeChannelId")
        if native:
            display_name = origin.get("label") or origin.get("sender") or None
            seen[native.upper()] = (ConversationType.DM, display_name)
    return sorted((cid, ctype, name) for cid, (ctype, name) in seen.items())


def _session_file_map(sessions_json: str) -> dict[str, str]:
    """Returns {session_uuid: sessionFile} from sessions.json.

    Falls back to '<_SESSION_DIR>/<uuid>.jsonl' for entries without sessionFile.
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for data in sessions.values():
        if not isinstance(data, dict):
            continue
        uuid = data.get("sessionId")
        if not uuid:
            continue
        out[uuid] = data.get("sessionFile") or f"{_SESSION_DIR}/{uuid}.jsonl"
    return out


def _dm_session(
    sessions_json: str, target_channel_id: str | None = None
) -> tuple[str, str] | None:
    """Returns (session_key, session_uuid) for the DM session if present.

    If target_channel_id is provided, only matches if nativeChannelId matches.
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return None
    data = sessions.get("agent:main:main") or {}
    if data.get("chatType") != "direct":
        return None
    origin = data.get("origin") or {}
    if origin.get("provider") != "slack":
        return None
    native = origin.get("nativeChannelId")
    if not native:
        return None
    if target_channel_id is not None and native.upper() != target_channel_id.upper():
        return None
    session_uuid = data.get("sessionId")
    if not session_uuid:
        return None
    return ("agent:main:main", session_uuid)


def _dm_thread_sessions(
    sessions_json: str, target_channel_id: str | None = None
) -> list[tuple[str, str]]:
    """Returns [(session_key, session_uuid)] for agent:main:main:thread:* sessions.

    Only returns sessions belonging to the DM channel identified by agent:main:main.
    If target_channel_id is given, filters to that channel.
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []
    dm_data = sessions.get("agent:main:main") or {}
    if dm_data.get("chatType") != "direct":
        return []
    origin = dm_data.get("origin") or {}
    if origin.get("provider") != "slack":
        return []
    dm_channel_id = origin.get("nativeChannelId")
    if not dm_channel_id:
        return []
    if (
        target_channel_id is not None
        and dm_channel_id.upper() != target_channel_id.upper()
    ):
        return []
    prefix = "agent:main:main:thread:"
    out: list[tuple[str, str]] = []
    for key, data in sessions.items():
        if not key.startswith(prefix):
            continue
        data = data or {}
        session_uuid = data.get("sessionId")
        if session_uuid:
            out.append((key, session_uuid))
    return out


@inject
@singleton
@dataclass
class ConversationSyncService:
    repository: ConversationRepository
    agent_repository: AgentRepository
    k8s: KubernetesClient
    config: Config
    _last_sync: dict[tuple[UUID, str], datetime] = field(
        init=False, default_factory=dict
    )
    _maps_cache: dict[UUID, tuple[dict[str, str], dict[str, str], datetime]] = field(
        init=False, default_factory=dict
    )
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _executor: ThreadPoolExecutor = field(
        init=False,
        default_factory=lambda: ThreadPoolExecutor(
            max_workers=_FIRE_AND_FORGET_MAX_WORKERS,
            thread_name_prefix="conv-sync",
        ),
    )

    def _safe_read_jsonl(self, pod_name: str, ns: str, file_path: str) -> str:
        try:
            return self.k8s.exec_command(pod_name, ns, ["cat", file_path])
        except Exception as e:
            logger.warning("Failed to read JSONL at %s: %s", file_path, e)
            return ""

    def _is_hermes(self, agent_id: UUID) -> bool:
        agent = self.agent_repository.get_by_id(agent_id)
        return agent is not None and agent.agent_type == AgentType.HERMES

    def _export_hermes_session(self, pod_name: str, ns: str, session_id: str) -> str:
        try:
            return self.k8s.exec_command(
                pod_name,
                ns,
                ["hermes", "sessions", "export", "--session-id", session_id, "-"],
            )
        except Exception as e:
            logger.warning("Failed to export hermes session %s: %s", session_id, e)
            return ""

    def _read_hermes_sessions_json(self, pod_name: str, ns: str) -> str:
        try:
            return self.k8s.exec_command(pod_name, ns, ["cat", HERMES_SESSIONS_PATH])
        except Exception as e:
            logger.warning("Failed to read hermes sessions.json: %s", e)
            return ""

    def _sync_hermes_channel(
        self,
        agent_id: UUID,
        pod_name: str,
        ns: str,
        channel_id: str,
    ) -> int:
        sessions_json = self._read_hermes_sessions_json(pod_name, ns)
        if not sessions_json:
            return 0
        targets = hermes_channel_sessions(sessions_json, channel_id)
        if not targets:
            return 0

        user_map, _ = self._platform_maps(agent_id)
        all_messages: list[AgentChatMessage] = []

        import json as _json

        try:
            sessions_data = _json.loads(sessions_json)
        except _json.JSONDecodeError:
            sessions_data = {}

        for session_key, session_id in targets:
            raw = self._export_hermes_session(pod_name, ns, session_id)
            if not raw:
                continue
            session_meta = sessions_data.get(session_key) or {}
            origin = session_meta.get("origin") or {}
            chat_type = session_meta.get("chat_type") or "channel"
            display_name = origin.get("user_name") if chat_type == "dm" else None
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                messages = parse_hermes_export(
                    agent_id,
                    session_key,
                    channel_id.upper(),
                    chat_type,
                    line,
                    user_map,
                    display_name,
                )
                all_messages.extend(messages)

        self.repository.upsert_messages(all_messages)
        return len(all_messages)

    def _platform_maps(self, agent_id: UUID) -> tuple[dict[str, str], dict[str, str]]:
        now = datetime.now(timezone.utc)
        with self._lock:
            cached = self._maps_cache.get(agent_id)
            if cached and (now - cached[2]) < _PLATFORM_MAPS_TTL:
                return cached[0], cached[1]

        agent = self.agent_repository.get_by_id(agent_id)
        if not (agent and self.config.agent_token_encryption_key):
            return {}, {}
        if agent.platform == AgentPlatform.TEAMS:
            return {}, {}
        try:
            slack_config = self.agent_repository.get_slack_config(agent_id)
            if not slack_config:
                return {}, {}
            bot_token = decrypt_token(
                slack_config.bot_token_encrypted,
                self.config.agent_token_encryption_key,
            )
            slack = SlackClient(bot_token)
            user_map, channel_map = slack.get_user_map(), slack.get_channel_map()
            with self._lock:
                self._maps_cache[agent_id] = (user_map, channel_map, now)
            return user_map, channel_map
        except Exception as e:
            logger.warning("Failed to fetch Slack maps for agent %s: %s", agent_id, e)
            return {}, {}

    def _pod_or_none(self, agent_id: UUID) -> tuple[str | None, str]:
        ns = self.config.k8s_namespace
        pod_name = self.k8s.get_pod_name_for_deployment(f"agent-{agent_id}", ns)
        return pod_name, ns

    def _read_sessions_json(self, pod_name: str, ns: str) -> str:
        try:
            return self.k8s.exec_command(pod_name, ns, ["cat", _SESSIONS_PATH])
        except Exception as e:
            logger.warning("Failed to read sessions.json: %s", e)
            return ""

    def _sync_session_subset(
        self,
        agent_id: UUID,
        pod_name: str,
        ns: str,
        sessions_json: str,
        session_uuids: list[str],
    ) -> int:
        if not session_uuids:
            return 0
        path_map = _session_file_map(sessions_json)
        paths = [path_map.get(u) or f"{_SESSION_DIR}/{u}.jsonl" for u in session_uuids]
        jsonl_cache: dict[str, str] = {}
        with ThreadPoolExecutor(
            max_workers=min(_PER_CHANNEL_READ_MAX_WORKERS, len(session_uuids))
        ) as pool:
            jsonl_cache = dict(
                zip(
                    session_uuids,
                    pool.map(
                        lambda p: self._safe_read_jsonl(pod_name, ns, p),
                        paths,
                    ),
                )
            )

        def get_jsonl(session_uuid: str) -> str:
            return jsonl_cache.get(session_uuid, "")

        user_map, channel_map = self._platform_maps(agent_id)
        messages = parse_sessions(
            agent_id, sessions_json, get_jsonl, user_map, channel_map
        )
        self.repository.upsert_messages(messages)
        return len(messages)

    def sync_channel(
        self, agent_id: UUID, channel_id: str, *, force: bool = False
    ) -> None:
        key = (agent_id, channel_id.upper())
        now = datetime.now(timezone.utc)
        if not force:
            with self._lock:
                last = self._last_sync.get(key)
                if last and (now - last) < _PER_CHANNEL_SYNC_INTERVAL:
                    return
                self._last_sync[key] = now

        pod_name, ns = self._pod_or_none(agent_id)
        if not pod_name:
            logger.info("No running pod for agent %s — skipping channel sync", agent_id)
            return

        if self._is_hermes(agent_id):
            n = self._sync_hermes_channel(agent_id, pod_name, ns, channel_id)
            logger.info(
                "Synced %d messages for hermes agent %s channel %s",
                n,
                agent_id,
                channel_id,
            )
            return

        sessions_json = self._read_sessions_json(pod_name, ns)
        if not sessions_json:
            return
        targets = _channel_sessions(sessions_json, channel_id)
        dm_target = _dm_session(sessions_json, channel_id)
        if dm_target:
            targets.append(dm_target)
        existing_uuids = {uid for _, uid in targets}
        for key, uid in _dm_thread_sessions(sessions_json, channel_id):
            if uid not in existing_uuids:
                targets.append((key, uid))
                existing_uuids.add(uid)
        session_uuids = [uid for _, uid in targets]
        n = self._sync_session_subset(
            agent_id, pod_name, ns, sessions_json, session_uuids
        )
        logger.info(
            "Synced %d messages for agent %s channel %s", n, agent_id, channel_id
        )

    def submit_sync_channel(self, agent_id: UUID, channel_id: str) -> None:
        """Fire-and-forget per-channel sync. Errors are swallowed."""

        def _run() -> None:
            try:
                self.sync_channel(agent_id, channel_id)
            except Exception as e:
                logger.warning(
                    "Background sync failed for agent %s channel %s: %s",
                    agent_id,
                    channel_id,
                    e,
                )

        try:
            self._executor.submit(_run)
        except RuntimeError as e:
            logger.warning("Sync executor rejected task: %s", e)

    def sync_all_channels(self, agent_id: UUID) -> None:
        """Synchronously sync every channel on the pod, max 4 in parallel.

        Used by stop_agent to flush before pod deletion.
        """
        pod_name, ns = self._pod_or_none(agent_id)
        if not pod_name:
            logger.info("No pod for agent %s — skipping full sync", agent_id)
            return

        if self._is_hermes(agent_id):
            sessions_json = self._read_hermes_sessions_json(pod_name, ns)
            conversations = (
                hermes_distinct_conversations(sessions_json) if sessions_json else []
            )
        else:
            sessions_json = self._read_sessions_json(pod_name, ns)
            conversations = (
                _distinct_pod_conversations(sessions_json) if sessions_json else []
            )

        if not conversations:
            return
        conversation_ids = [conv[0] for conv in conversations]

        def _one(cid: str) -> None:
            try:
                self.sync_channel(agent_id, cid, force=True)
            except Exception as e:
                logger.warning(
                    "sync_all: channel %s failed for agent %s: %s", cid, agent_id, e
                )

        with ThreadPoolExecutor(
            max_workers=min(_STOP_SYNC_MAX_WORKERS, len(conversation_ids))
        ) as pool:
            list(pool.map(_one, conversation_ids))


def _group_into_threads(
    messages: list[AgentChatMessage],
    cursor: ConversationsCursor,
    page_size: int,
) -> tuple[list[ConversationThreadRead], bool, ConversationsCursor | None]:
    """Group flat messages into thread pages, paginated by root-message count.

    Handles two cases:
    - Messages with thread_id=None are potential standalone roots.
    - Messages with a non-None thread_id are grouped by that value. Within each
      group the earliest message (or a thread_id=None message within 5s of the
      Slack ts float) is the root.  Any None-group messages that fall between
      that root and the first non-None reply are also included as replies (handles
      the DM case where the agent's first response is stored with thread_id=None).
    """
    by_thread: dict[str | None, list[AgentChatMessage]] = {}
    for m in messages:
        by_thread.setdefault(m.thread_id, []).append(m)

    null_msgs = sorted(by_thread.pop(None, []), key=lambda m: (m.occurred_at, m.id))
    used_null_ids: set = set()

    raw_threads: list[tuple[AgentChatMessage, list[AgentChatMessage]]] = []

    for tid, msgs in by_thread.items():
        if tid is None:
            continue
        try:
            tid_f = float(tid)
        except ValueError, TypeError:
            continue

        msgs_sorted = sorted(msgs, key=lambda m: (m.occurred_at, m.id))

        # Try to find a null-group message as the root (within 5s of Slack ts).
        root: AgentChatMessage | None = None
        for nm in null_msgs:
            if nm.id in used_null_ids:
                continue
            if abs(nm.occurred_at.timestamp() - tid_f) <= 5.0:
                root = nm
                used_null_ids.add(nm.id)
                break

        # Collect null-group messages between the root and the first non-null
        # reply (e.g. the agent's first DM response stored with thread_id=None).
        extra_null_replies: list[AgentChatMessage] = []
        if root is not None:
            first_reply_ts = msgs_sorted[0].occurred_at if msgs_sorted else None
            for nm in null_msgs:
                if nm.id in used_null_ids:
                    continue
                if nm.occurred_at > root.occurred_at and (
                    first_reply_ts is None or nm.occurred_at <= first_reply_ts
                ):
                    extra_null_replies.append(nm)
                    used_null_ids.add(nm.id)

        if root is None:
            # No null candidate: first message in the group is the root.
            root = msgs_sorted[0]
            replies = msgs_sorted[1:]
        else:
            replies = extra_null_replies + msgs_sorted

        replies.sort(key=lambda m: (m.occurred_at, m.id))
        raw_threads.append((root, replies))

    # Remaining null messages are standalone threads (e.g. plain DM messages).
    for nm in null_msgs:
        if nm.id not in used_null_ids:
            raw_threads.append((nm, []))

    # Sort all threads newest-first for cursor pagination.
    raw_threads.sort(key=lambda t: (t[0].occurred_at, t[0].id), reverse=True)

    if cursor.before_occurred_at is not None:
        before_ts = cursor.before_occurred_at
        before_id = cursor.before_id
        if before_id is not None:
            raw_threads = [
                t
                for t in raw_threads
                if t[0].occurred_at < before_ts
                or (t[0].occurred_at == before_ts and t[0].id < before_id)
            ]
        else:
            raw_threads = [t for t in raw_threads if t[0].occurred_at < before_ts]

    has_more = len(raw_threads) > page_size
    page_threads = raw_threads[:page_size]

    # Return threads in oldest-first display order within the page.
    threads: list[ConversationThreadRead] = []
    for root, replies in reversed(page_threads):
        threads.append(
            ConversationThreadRead(
                root=ConversationMessageRead.model_validate(root),
                replies=[ConversationMessageRead.model_validate(r) for r in replies],
            )
        )

    next_cursor: ConversationsCursor | None = None
    if has_more and page_threads:
        oldest_root = page_threads[-1][0]
        next_cursor = ConversationsCursor(
            before_occurred_at=oldest_root.occurred_at,
            before_id=oldest_root.id,
        )

    return threads, has_more, next_cursor


@inject
@singleton
@dataclass
class ConversationService:
    repository: ConversationRepository
    agent_repository: AgentRepository
    sync_service: ConversationSyncService
    k8s: KubernetesClient
    config: Config

    def list_channels(
        self, agent_id: UUID, org_id: UUID
    ) -> list[ConversationChannelRead]:
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

        db_channels = self.repository.distinct_channels(agent_id)
        merged: dict[str, tuple[str | None, ConversationType]] = {
            cid: (name, ctype) for cid, name, ctype in db_channels
        }

        if agent.status == AgentStatus.RUNNING:
            try:
                pod_name, ns = self.sync_service._pod_or_none(agent_id)
                if pod_name:
                    if agent.agent_type == AgentType.HERMES:
                        sessions_json = self.sync_service._read_hermes_sessions_json(
                            pod_name, ns
                        )
                        pod_conversations = (
                            hermes_distinct_conversations(sessions_json)
                            if sessions_json
                            else []
                        )
                        for cid, ctype, display_name in pod_conversations:
                            if cid not in merged or merged[cid][0] is None:
                                merged[cid] = (display_name, ctype)
                    else:
                        sessions_json = self.sync_service._read_sessions_json(
                            pod_name, ns
                        )
                        if sessions_json:
                            pod_conversations = _distinct_pod_conversations(
                                sessions_json
                            )
                            slack_channel_map: dict[str, str] = {}
                            if pod_conversations:
                                _, slack_channel_map = self.sync_service._platform_maps(
                                    agent_id
                                )
                            for cid, ctype, display_name in pod_conversations:
                                if cid not in merged or merged[cid][0] is None:
                                    name = slack_channel_map.get(cid) or display_name
                                    merged[cid] = (name, ctype)
            except Exception as e:
                logger.warning(
                    "list_channels: pod read failed for agent %s: %s", agent_id, e
                )

        return [
            ConversationChannelRead(
                channel_id=cid, channel_name=name, conversation_type=ctype
            )
            for cid, (name, ctype) in sorted(merged.items())
        ]

    def list_threads(
        self,
        agent_id: UUID,
        org_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        cursor: ConversationsCursor,
        page_size: int,
    ) -> ConversationThreadsPage:
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

        if agent.status == AgentStatus.RUNNING:
            self.sync_service.submit_sync_channel(agent_id, channel_id)

        messages = self.repository.find_all_channel_messages(
            agent_id=agent_id,
            channel_id=channel_id.upper(),
            filter=filter,
        )
        threads, has_more, next_cursor = _group_into_threads(
            messages, cursor, page_size
        )
        return ConversationThreadsPage(
            threads=threads,
            has_more=has_more,
            next_cursor=next_cursor,
        )


# Re-exported for backward compatibility — tests still reference these helpers.
__all__ = [
    "ConversationService",
    "ConversationSyncService",
    "AgentChatMessage",
]
