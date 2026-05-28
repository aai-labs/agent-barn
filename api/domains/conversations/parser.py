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
_MENTION_RE = re.compile(r"<@(U\w+)>")
_TS_FMT = "%Y-%m-%d %H:%M:%S UTC"

_SESSION_PREFIXES = (
    "agent:main:slack:channel:",
    "agent:main:msteams:channel:",
    "agent:main:msteams:group:",
)


def _parse_occurred_at(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, _TS_FMT).replace(tzinfo=timezone.utc)


def _parse_iso(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _resolve_mentions(text: str, user_map: dict[str, str]) -> str:
    return _MENTION_RE.sub(lambda m: f"@{user_map.get(m.group(1), m.group(1))}", text)


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
            m = _INBOUND_RE.search(first_line) or _INBOUND_TEAMS_RE.search(first_line)
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
                    thread_id=None,
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
                openclaw_msg_id=line["id"],
                session_key=session_key,
                channel_id=conversation_id,
                thread_id=None,
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

    # DM session: keyed as agent:main:main with chatType == "direct"
    dm_session_data = sessions.get("agent:main:main")
    if dm_session_data:
        origin = dm_session_data.get("origin") or {}
        if (
            dm_session_data.get("chatType") == "direct"
            and origin.get("provider") == "slack"
        ):
            conversation_id = (origin.get("nativeChannelId") or "").upper()
            session_uuid = dm_session_data.get("sessionId")
            display_name = origin.get("label") or origin.get("sender") or None
            if conversation_id and session_uuid:
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
                        conversation_id,
                        jsonl_text,
                        user_map,
                        display_name,
                    )
                    all_messages.extend(dm_messages)

    return all_messages
