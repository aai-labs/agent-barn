"""Assemble a source Agent's recent conversations into bounded plain-text transcripts.

Runtimes report Conversation Messages under a conversation ``session_key`` and Tool
Calls under their own runtime session ID, and the two never match. A runtime session
runs inside the conversation turn that started it, so each Tool Call session is
attached to the conversation whose time span contains it.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from api.domains.conversations.models import MessageDirection

# A runtime session may start a moment before the first mirrored message is stored
# and finish just after the reply is.
TOOL_SESSION_SLACK = timedelta(seconds=30)

MAX_MESSAGES_PER_SESSION = 200
MAX_TOOL_CALLS_PER_SESSION = 300
MESSAGE_CHARS = 4_000
TOOL_ARGUMENT_CHARS = 1_000
TOOL_RESULT_CHARS = 1_500
COMPACT_TOOL_CHARS = 300
SESSION_CHARS = 40_000
# Model tokenizers average roughly four characters of English per token.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ConversationSpan:
    session_key: str
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class ToolSessionSpan:
    session_id: str
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class MessageRow:
    session_key: str
    direction: MessageDirection
    sender_name: str | None
    content: str
    occurred_at: datetime


@dataclass(frozen=True)
class ToolCallRow:
    session_id: str
    tool_name: str
    arguments: Any
    result: Any
    status: str
    occurred_at: datetime


@dataclass(frozen=True)
class SessionTranscript:
    session_key: str
    started_at: datetime
    ended_at: datetime
    message_count: int
    tool_call_count: int
    text: str


def assign_tool_sessions(conversations: list[ConversationSpan], tool_sessions: list[ToolSessionSpan]) -> dict[str, str]:
    """Map each Tool Call session ID to the conversation it ran in.

    A tool session belongs to the conversation whose span, widened by the slack,
    contains it; among several, the shortest span is the closest fit. A session that
    no conversation contains, such as startup or internal maintenance work, is left out.
    """
    assigned: dict[str, str] = {}
    for tool_session in tool_sessions:
        containing = [
            conversation
            for conversation in conversations
            if conversation.started_at - TOOL_SESSION_SLACK <= tool_session.started_at
            and tool_session.ended_at <= conversation.ended_at + TOOL_SESSION_SLACK
        ]
        if containing:
            closest = min(containing, key=lambda c: (c.ended_at - c.started_at, c.session_key))
            assigned[tool_session.session_id] = closest.session_key
    return assigned


def render_transcripts(
    conversations: list[ConversationSpan],
    messages: list[MessageRow],
    tool_calls: list[ToolCallRow],
    tool_session_owner: dict[str, str],
) -> list[SessionTranscript]:
    """One transcript per conversation, in the order the conversations were given."""
    messages_by_session: dict[str, list[MessageRow]] = defaultdict(list)
    for message in messages:
        messages_by_session[message.session_key].append(message)
    calls_by_session: dict[str, list[ToolCallRow]] = defaultdict(list)
    for call in tool_calls:
        owner = tool_session_owner.get(call.session_id)
        if owner is not None:
            calls_by_session[owner].append(call)

    transcripts = []
    for conversation in conversations:
        session_messages = messages_by_session[conversation.session_key]
        session_calls = calls_by_session[conversation.session_key]
        text = _render(conversation, session_messages, session_calls, TOOL_ARGUMENT_CHARS, TOOL_RESULT_CHARS)
        if len(text) > SESSION_CHARS:
            text = _render(conversation, session_messages, session_calls, COMPACT_TOOL_CHARS, COMPACT_TOOL_CHARS)
        if len(text) > SESSION_CHARS:
            text = text[:SESSION_CHARS] + "\n[transcript truncated]"
        transcripts.append(
            SessionTranscript(
                session_key=conversation.session_key,
                started_at=conversation.started_at,
                ended_at=conversation.ended_at,
                message_count=len(session_messages),
                tool_call_count=len(session_calls),
                text=text,
            )
        )
    return transcripts


def estimated_tokens(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN)


def _render(
    conversation: ConversationSpan,
    messages: list[MessageRow],
    calls: list[ToolCallRow],
    argument_chars: int,
    result_chars: int,
) -> str:
    entries: list[tuple[datetime, int, str]] = []
    for message in messages:
        if message.direction == MessageDirection.INBOUND:
            speaker = f"Person ({message.sender_name})" if message.sender_name else "Person"
        else:
            speaker = "Agent"
        entries.append((message.occurred_at, 0, f"{speaker}: {_clip(message.content, MESSAGE_CHARS)}"))
    for call in calls:
        lines = [f"Tool {call.tool_name} ({call.status.lower()})"]
        lines.append(f"  arguments: {_clip(_as_text(call.arguments), argument_chars)}")
        if call.result is not None:
            lines.append(f"  result: {_clip(_as_text(call.result), result_chars)}")
        entries.append((call.occurred_at, 1, "\n".join(lines)))
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    header = f"Conversation from {conversation.started_at:%Y-%m-%d %H:%M} UTC"
    body = [f"[{occurred_at:%H:%M:%S}] {line}" for occurred_at, _, line in entries]
    return "\n".join([header, *body])


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [… {len(text) - limit} more characters]"
