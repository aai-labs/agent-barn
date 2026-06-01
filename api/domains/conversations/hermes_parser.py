"""Hermes session parser — no I/O, no DB, no k8s."""

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationType,
    MessageDirection,
)
from api.domains.tool_calls.jsonl_parser import ParsedToolCall, ParsedToolResult

logger = logging.getLogger(__name__)

HERMES_SESSIONS_PATH = "/opt/data/sessions/sessions.json"

_DM_PREFIXES = ("agent:main:slack:dm:",)
_CHANNEL_PREFIXES = ("agent:main:slack:channel:",)
_ALL_PREFIXES = _DM_PREFIXES + _CHANNEL_PREFIXES


def _chat_type_from_key(session_key: str) -> str:
    for p in _DM_PREFIXES:
        if session_key.startswith(p):
            return "dm"
    return "channel"


def _channel_id_from_session(session_data: dict) -> str | None:
    origin = session_data.get("origin") or {}
    return (origin.get("chat_id") or "").upper() or None


def hermes_distinct_conversations(
    sessions_json: str,
) -> list[tuple[str, ConversationType, str | None]]:
    """Return distinct (channel_id, ConversationType, display_name) from sessions.json."""
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []

    seen: dict[str, tuple[ConversationType, str | None]] = {}
    for key, data in sessions.items():
        if not isinstance(data, dict):
            continue
        if not any(key.startswith(p) for p in _ALL_PREFIXES):
            continue
        channel_id = _channel_id_from_session(data)
        if not channel_id:
            continue
        chat_type = data.get("chat_type") or _chat_type_from_key(key)
        ctype = ConversationType.DM if chat_type == "dm" else ConversationType.CHANNEL
        origin = data.get("origin") or {}
        display_name = origin.get("user_name") if ctype == ConversationType.DM else None
        if channel_id not in seen:
            seen[channel_id] = (ctype, display_name)

    return sorted((cid, ctype, name) for cid, (ctype, name) in seen.items())


def hermes_channel_sessions(
    sessions_json: str,
    target_channel_id: str | None,
) -> list[tuple[str, str]]:
    """Return [(session_key, hermes_session_id)] matching target_channel_id."""
    try:
        sessions = json.loads(sessions_json)
    except json.JSONDecodeError:
        return []

    target_upper = target_channel_id.upper() if target_channel_id else None
    out: list[tuple[str, str]] = []
    for key, data in sessions.items():
        if not isinstance(data, dict):
            continue
        if not any(key.startswith(p) for p in _ALL_PREFIXES):
            continue
        session_id = data.get("session_id")
        if not session_id:
            continue
        channel_id = _channel_id_from_session(data)
        if not channel_id:
            continue
        if target_upper is not None and channel_id != target_upper:
            continue
        out.append((key, session_id))
    return out


def _unix_to_utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_hermes_export(
    agent_id: UUID,
    session_key: str,
    channel_id: str,
    chat_type: str,
    export_json: str,
    user_map: dict[str, str] | None = None,
    display_name: str | None = None,
) -> list[AgentChatMessage]:
    """Parse messages from a single `hermes sessions export --session-id` JSON line."""
    try:
        session = json.loads(export_json)
    except json.JSONDecodeError:
        logger.warning("Failed to parse hermes export for session_key=%s", session_key)
        return []

    session_id = session.get("id", "")
    raw_messages = session.get("messages") or []
    ctype = ConversationType.DM if chat_type == "dm" else ConversationType.CHANNEL

    sender_id: str | None = session.get("user_id")
    sender_name: str | None = display_name

    out: list[AgentChatMessage] = []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if not content or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        ts = msg.get("timestamp")
        if ts is None:
            continue
        try:
            occurred_at = _unix_to_utc(float(ts))
        except (ValueError, OSError):
            continue

        msg_id = msg.get("id")
        dedup_id = f"hermes:{session_id}:{msg_id}"

        direction = MessageDirection.INBOUND if role == "user" else MessageDirection.OUTBOUND
        out.append(
            AgentChatMessage(
                agent_id=agent_id,
                openclaw_msg_id=dedup_id,
                session_key=session_key,
                channel_id=channel_id,
                thread_id=None,
                direction=direction,
                conversation_type=ctype,
                sender_id=sender_id if role == "user" else None,
                sender_name=(user_map or {}).get(sender_id or "", sender_name) if role == "user" else None,
                channel_name=display_name,
                content=content,
                occurred_at=occurred_at,
            )
        )
    return out


def parse_hermes_export_tool_calls(
    export_json: str,
    session_id: str,
) -> tuple[list[ParsedToolCall], list[ParsedToolResult]]:
    """Extract tool calls and results from a hermes session export JSON line."""
    try:
        session = json.loads(export_json)
    except json.JSONDecodeError:
        return [], []

    tool_calls: list[ParsedToolCall] = []
    tool_results: list[ParsedToolResult] = []

    for msg in session.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        ts = msg.get("timestamp")
        if ts is None:
            continue
        try:
            occurred_at = _unix_to_utc(float(ts))
        except (ValueError, OSError):
            continue

        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                tc_id = tc.get("id")
                name = fn.get("name")
                if not tc_id or not name:
                    continue
                raw_args = fn.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    arguments = {"_raw": raw_args}
                tool_calls.append(
                    ParsedToolCall(
                        external_id=tc_id,
                        session_id=session_id,
                        tool_name=name,
                        arguments=arguments,
                        occurred_at=occurred_at,
                    )
                )

        elif role == "tool":
            tc_id = msg.get("tool_call_id")
            if not tc_id:
                continue
            content = msg.get("content")
            result = [{"type": "text", "text": content}] if isinstance(content, str) else None
            tool_results.append(
                ParsedToolResult(
                    external_id=tc_id,
                    result=result,
                    is_error=False,
                    completed_at=occurred_at,
                )
            )

    return tool_calls, tool_results
