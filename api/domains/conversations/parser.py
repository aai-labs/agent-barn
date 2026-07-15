"""
Pure JSONL parser — no I/O, no DB, no k8s.

Given the text of sessions.json and a callable that returns JSONL text for a
session UUID, returns AgentChatMessage objects ready for upsert.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationType,
    MessageDirection,
)

logger = logging.getLogger(__name__)

_INBOUND_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] "
    r"Slack message in #(\S+) from (\w+): (.+)",
    re.DOTALL,
)
_DM_INBOUND_RE = re.compile(
    r"System \(untrusted\): \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] "
    r"Slack DM from ([^:]+): (.+)",
    re.DOTALL,
)
_DM_SENDER_RE = re.compile(r'"sender_id"\s*:\s*"(U\w+)"')
# Exact format may differ at runtime — adjust regex after inspecting live Teams JSONL output.
_INBOUND_TEAMS_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] "
    r"Teams message in (.+?) from (\S+): (.+)",
    re.DOTALL,
)
_INBOUND_TELEGRAM_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] "
    r"Telegram message in (.+?) from (\S+): (.+)",
    re.DOTALL,
)
_MENTION_RE = re.compile(r"<@(U\w+)>")
_TS_FMT = "%Y-%m-%d %H:%M:%S UTC"

_SESSION_PREFIXES = (
    "agent:main:slack:channel:",
    "agent:main:msteams:channel:",
    "agent:main:msteams:group:",
    "agent:main:telegram:channel:",
    "agent:main:telegram:group:",
    "agent:main:telegram:dm:",
)


def _parse_occurred_at(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, _TS_FMT).replace(tzinfo=timezone.utc)


def _parse_iso(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _resolve_mentions(text: str, user_map: dict[str, str]) -> str:
    return _MENTION_RE.sub(lambda m: f"@{user_map.get(m.group(1), m.group(1))}", text)


_JSON_META_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _runtime_context_meta(content: str) -> dict | None:
    """Return the conversation-info JSON block embedded in a runtime-context
    message — the first fenced ```json block that carries Slack thread ids."""
    for match in _JSON_META_RE.finditer(content):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and ("topic_id" in obj or "message_id" in obj):
            return obj
    return None


def _accumulate_thread_links(
    jsonl_text: str,
    session_topic: str | None,
    root_of: dict[str, str],
    link: dict[str, str],
) -> None:
    """Learn the canonical Slack thread root from one session's JSONL.

    openclaw buckets sessions by whatever threadId the agent passes to the
    `message` send tool, which is often a non-root reply ts — so one Slack
    thread fragments across several sessions. Two maps (keyed by Slack ts)
    let us undo that:
    - root_of[ts]: thread root, from inbound runtime-context metadata
      (message_id -> topic_id).
    - link[ts] -> parent ts: a posted message (toolResult.messageId) hangs
      under the threadId the agent replied to (empty threadId == the
      session's own topic).
    """
    tool_threads: dict[str, str] = {}  # toolCallId -> threadId used (or session topic)
    tool_results: dict[str, str] = {}  # toolCallId -> posted Slack messageId

    for raw_line in jsonl_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            line = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        if (
            line.get("type") == "custom_message"
            and line.get("customType") == "openclaw.runtime-context"
        ):
            meta = _runtime_context_meta(line.get("content", ""))
            if meta:
                message_id = meta.get("message_id")
                topic_id = meta.get("topic_id") or meta.get("reply_to_id")
                if message_id and topic_id:
                    root_of[message_id] = topic_id
                    root_of.setdefault(topic_id, topic_id)
            continue

        if line.get("type") != "message":
            continue
        msg = line.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") not in ("toolCall", "tool_use", "tool_call"):
                    continue
                if block.get("name") != "message":
                    continue
                args = block.get("arguments") or block.get("input") or {}
                if not isinstance(args, dict) or args.get("action") != "send":
                    continue
                call_id = block.get("id")
                if not call_id:
                    continue
                thread_arg = (args.get("threadId") or "").strip()
                tool_threads[call_id] = thread_arg or (session_topic or "")
        elif role == "toolResult":
            call_id = msg.get("toolCallId")
            details = msg.get("details")
            result = details.get("result") if isinstance(details, dict) else None
            message_id = result.get("messageId") if isinstance(result, dict) else None
            if call_id and message_id:
                tool_results[call_id] = message_id

    for call_id, posted_id in tool_results.items():
        parent = tool_threads.get(call_id)
        if parent:
            link[posted_id] = parent


def _resolve_root(ts: str, root_of: dict[str, str], link: dict[str, str]) -> str:
    """Resolve a thread id to its canonical Slack thread root, following
    inbound topic mappings and outbound reply links. Falls back to the input
    when nothing is known (treated as its own root)."""
    seen: set[str] = set()
    cur = ts
    while cur and cur not in seen:
        seen.add(cur)
        if cur in root_of:
            return root_of[cur]
        nxt = link.get(cur)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return cur


def _parse_jsonl(
    agent_id: UUID,
    session_key: str,
    channel_id: str,
    thread_id: str | None,
    jsonl_text: str,
    user_map: dict[str, str] | None = None,
    channel_map: dict[str, str] | None = None,
) -> list[AgentChatMessage]:
    messages: list[AgentChatMessage] = []

    for raw_line in jsonl_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            line = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        line_type = line.get("type", "")
        line_id = line.get("id", "")
        if not line_id:
            continue

        # --- INBOUND ---
        if (
            line_type == "custom_message"
            and line.get("customType") == "openclaw.runtime-context"
        ):
            content_raw = line.get("content", "")
            first_line = content_raw.split("\n")[0]
            m = _INBOUND_RE.search(first_line) or _INBOUND_TEAMS_RE.search(first_line) or _INBOUND_TELEGRAM_RE.search(first_line)
            if not m:
                continue
            ts_str, _raw_channel, sender_id, text = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4).strip(),
            )
            try:
                occurred_at = _parse_occurred_at(ts_str)
            except ValueError:
                continue
            resolved_channel = (channel_map or {}).get(channel_id) or _raw_channel
            resolved_sender = (user_map or {}).get(sender_id)
            resolved_text = _resolve_mentions(text, user_map or {})
            messages.append(
                AgentChatMessage(
                    agent_id=agent_id,
                    openclaw_msg_id=line_id,
                    session_key=session_key,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    direction=MessageDirection.INBOUND,
                    conversation_type=ConversationType.CHANNEL,
                    sender_id=sender_id,
                    sender_name=resolved_sender,
                    channel_name=resolved_channel,
                    content=resolved_text,
                    occurred_at=occurred_at,
                )
            )

        # --- OUTBOUND ---
        elif line_type == "message":
            msg = line.get("message", {})
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            if msg.get("model") != "delivery-mirror":
                continue
            content_blocks = msg.get("content", [])
            if not isinstance(content_blocks, list) or not content_blocks:
                continue
            block = content_blocks[0]
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text", "").strip()
            if not text or text == "HEARTBEAT_OK":
                continue
            try:
                occurred_at = _parse_iso(line.get("timestamp", ""))
            except ValueError, TypeError:
                continue
            messages.append(
                AgentChatMessage(
                    agent_id=agent_id,
                    openclaw_msg_id=line_id,
                    session_key=session_key,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    direction=MessageDirection.OUTBOUND,
                    conversation_type=ConversationType.CHANNEL,
                    sender_id=None,
                    sender_name=None,
                    content=_resolve_mentions(text, user_map or {}),
                    occurred_at=occurred_at,
                )
            )

    return messages


def _parse_dm_jsonl(
    agent_id: UUID,
    session_key: str,
    conversation_id: str,
    jsonl_text: str,
    user_map: dict[str, str] | None = None,
    display_name: str | None = None,
    thread_id: str | None = None,
) -> list[AgentChatMessage]:
    custom_messages: list[dict] = []
    outbound_lines: list[dict] = []

    for raw_line in jsonl_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            line = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        line_type = line.get("type", "")
        if (
            line_type == "custom_message"
            and line.get("customType") == "openclaw.runtime-context"
        ):
            custom_messages.append(line)
        elif line_type == "message":
            msg = line.get("message", {})
            if (
                isinstance(msg, dict)
                and msg.get("role") == "assistant"
                and line.get("id")
            ):
                outbound_lines.append(line)

    messages: list[AgentChatMessage] = []

    # INBOUND: scan ALL custom_messages — each may cover a different slice of the
    # conversation. Deduplicate by msg_id (dm:{channel_id}:{ts_str}).
    seen_msg_ids: set[str] = set()
    sender_id: str | None = None
    channel_display_name: str | None = display_name
    inbound_messages: list[AgentChatMessage] = []

    for cm in custom_messages:
        content_raw = cm.get("content", "")
        if sender_id is None:
            sender_id_match = _DM_SENDER_RE.search(content_raw)
            if sender_id_match:
                sender_id = sender_id_match.group(1)
        for line_text in content_raw.splitlines():
            m = _DM_INBOUND_RE.match(line_text.strip())
            if not m:
                continue
            ts_str, sender_name, text = (
                m.group(1),
                m.group(2).strip(),
                m.group(3).strip(),
            )
            msg_id = f"dm:{conversation_id}:{ts_str}"
            if msg_id in seen_msg_ids:
                continue
            seen_msg_ids.add(msg_id)
            if channel_display_name is None:
                channel_display_name = sender_name
            try:
                occurred_at = _parse_occurred_at(ts_str)
            except ValueError:
                continue
            inbound_messages.append(
                AgentChatMessage(
                    agent_id=agent_id,
                    openclaw_msg_id=msg_id,
                    session_key=session_key,
                    channel_id=conversation_id,
                    thread_id=thread_id,
                    direction=MessageDirection.INBOUND,
                    conversation_type=ConversationType.DM,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    channel_name=channel_display_name,
                    content=text,
                    occurred_at=occurred_at,
                )
            )

    # Back-fill sender_id on inbound messages that were created before sender_id was found
    if sender_id is not None:
        for msg in inbound_messages:
            if msg.sender_id is None:
                msg.sender_id = sender_id

    messages.extend(inbound_messages)

    # OUTBOUND: nested under `message` key, `timestamp` field (same structure as channels)
    for line in outbound_lines:
        msg = line.get("message", {})
        content_blocks = msg.get("content", [])
        if not isinstance(content_blocks, list):
            continue
        # Find first text block — DM thread responses may lead with a thinking block.
        block = next(
            (
                b
                for b in content_blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ),
            None,
        )
        if block is None:
            continue
        text = block.get("text", "").strip()
        if not text or text == "HEARTBEAT_OK":
            continue
        try:
            occurred_at = _parse_iso(line.get("timestamp", ""))
        except ValueError, TypeError:
            continue
        messages.append(
            AgentChatMessage(
                agent_id=agent_id,
                openclaw_msg_id=line["id"],
                session_key=session_key,
                channel_id=conversation_id,
                thread_id=thread_id,
                direction=MessageDirection.OUTBOUND,
                conversation_type=ConversationType.DM,
                sender_id=None,
                sender_name=None,
                channel_name=channel_display_name,
                content=_resolve_mentions(text, user_map or {}),
                occurred_at=occurred_at,
            )
        )

    return messages


def parse_sessions(
    agent_id: UUID,
    sessions_json: str,
    get_jsonl: Callable[[str], str],
    user_map: dict[str, str] | None = None,
    channel_map: dict[str, str] | None = None,
) -> list[AgentChatMessage]:
    """
    Parse all platform sessions for an agent.

    sessions_json: text content of sessions.json from the pod
    get_jsonl: callable(session_uuid) -> JSONL text for that session
    user_map: optional {user_id: display_name} for resolving sender names and @mentions
    channel_map: optional {channel_id: channel_name} for resolving channel names
    """
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        logger.warning("Failed to parse sessions.json for agent %s", agent_id)
        return []

    all_messages: list[AgentChatMessage] = []
    root_of: dict[str, str] = {}
    link: dict[str, str] = {}

    for session_key, session_data in sessions.items():
        if not any(session_key.startswith(p) for p in _SESSION_PREFIXES):
            continue

        session_uuid = session_data.get("sessionId")
        if not session_uuid:
            continue

        origin = session_data.get("origin") or {}
        channel_id = (
            origin.get("nativeChannelId") or session_data.get("groupId") or ""
        ).upper()
        if not channel_id:
            continue
        thread_id: str | None = origin.get("threadId") or None

        try:
            jsonl_text = get_jsonl(session_uuid)
        except Exception as e:
            logger.warning("Failed to read JSONL for session %s: %s", session_uuid, e)
            continue

        messages = _parse_jsonl(
            agent_id,
            session_key,
            channel_id,
            thread_id,
            jsonl_text,
            user_map,
            channel_map,
        )
        all_messages.extend(messages)
        _accumulate_thread_links(jsonl_text, thread_id, root_of, link)

    # DM session: keyed as agent:main:main with chatType == "direct"
    dm_conversation_id: str | None = None
    dm_display_name: str | None = None
    dm_session_data = sessions.get("agent:main:main")
    if dm_session_data:
        origin = dm_session_data.get("origin") or {}
        if (
            dm_session_data.get("chatType") == "direct"
            and origin.get("provider") == "slack"
        ):
            dm_conversation_id = (origin.get("nativeChannelId") or "").upper() or None
            session_uuid = dm_session_data.get("sessionId")
            dm_display_name = origin.get("label") or origin.get("sender") or None
            if dm_conversation_id and session_uuid:
                try:
                    jsonl_text = get_jsonl(session_uuid)
                except Exception as e:
                    logger.warning(
                        "Failed to read DM JSONL for session %s: %s", session_uuid, e
                    )
                    jsonl_text = ""
                if jsonl_text:
                    dm_messages = _parse_dm_jsonl(
                        agent_id,
                        "agent:main:main",
                        dm_conversation_id,
                        jsonl_text,
                        user_map,
                        dm_display_name,
                    )
                    all_messages.extend(dm_messages)

    # DM thread sessions: agent:main:main:thread:<ts>
    if dm_conversation_id:
        _dm_thread_prefix = "agent:main:main:thread:"
        for thread_session_key, thread_session_data in sessions.items():
            if not thread_session_key.startswith(_dm_thread_prefix):
                continue
            thread_ts = thread_session_key[len(_dm_thread_prefix) :]
            if not isinstance(thread_session_data, dict):
                continue
            thread_uuid = thread_session_data.get("sessionId")
            if not thread_uuid:
                continue
            try:
                jsonl_text = get_jsonl(thread_uuid)
            except Exception as e:
                logger.warning(
                    "Failed to read DM thread JSONL for session %s: %s",
                    thread_uuid,
                    e,
                )
                jsonl_text = ""
            if jsonl_text:
                dm_thread_messages = _parse_dm_jsonl(
                    agent_id,
                    thread_session_key,
                    dm_conversation_id,
                    jsonl_text,
                    user_map,
                    dm_display_name,
                    thread_id=thread_ts,
                )
                all_messages.extend(dm_thread_messages)

    # Collapse openclaw session fragmentation: the agent sometimes replies with
    # a non-root threadId, spreading one Slack thread across several sessions.
    # Remap each channel message's thread_id to the canonical Slack thread root.
    if root_of or link:
        for message in all_messages:
            if message.thread_id is not None:
                message.thread_id = _resolve_root(message.thread_id, root_of, link)

    return all_messages
