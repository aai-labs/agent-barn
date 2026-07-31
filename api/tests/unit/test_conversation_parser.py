"""Unit tests for the conversation JSONL parser — no I/O, no DB, no k8s."""

import json
from uuid import UUID

from api.domains.conversations.hermes_parser import (
    hermes_channel_sessions,
    hermes_distinct_conversations,
)
from api.domains.conversations.models import ConversationType, MessageDirection
from api.domains.conversations.parser import parse_sessions

_AGENT_ID = UUID("00000000-0000-0000-0000-000000000001")

_CHANNEL_SESSION_KEY = "agent:main:slack:channel:c0b4w57jvez"
_THREAD_SESSION_KEY = "agent:main:slack:channel:c0b4w57jvez:thread:1779269814.824809"

_SESSIONS_JSON = json.dumps(
    {
        _CHANNEL_SESSION_KEY: {
            "sessionId": "aaaa-bbbb",
            "chatType": "channel",
            "groupId": "c0b4w57jvez",
            "origin": {"nativeChannelId": "C0B4W57JVEZ", "threadId": None},
        },
        _THREAD_SESSION_KEY: {
            "sessionId": "cccc-dddd",
            "groupId": "c0b4w57jvez",
            "origin": {
                "nativeChannelId": "C0B4W57JVEZ",
                "threadId": "1779269814.824809",
            },
        },
    }
)

_INBOUND_LINE = json.dumps(
    {
        "id": "msg-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 12:00:00 UTC] Slack message in #general from U12345: Hello agent!",
    }
)

_OUTBOUND_LINE = json.dumps(
    {
        "id": "msg-002",
        "type": "message",
        "timestamp": "2025-05-01T12:00:05Z",
        "message": {
            "role": "assistant",
            "model": "delivery-mirror",
            "content": [{"type": "text", "text": "Hello! How can I help?"}],
        },
    }
)

_IRRELEVANT_LINE = json.dumps(
    {
        "id": "msg-003",
        "type": "message",
        "timestamp": "2025-05-01T12:00:01Z",
        "message": {
            "role": "assistant",
            "model": "claude-opus",  # not delivery-mirror
            "content": [{"type": "text", "text": "Internal thinking..."}],
        },
    }
)

_CHANNEL_JSONL = f"{_INBOUND_LINE}\n{_OUTBOUND_LINE}\n{_IRRELEVANT_LINE}"
_THREAD_JSONL = json.dumps(
    {
        "id": "msg-thread-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 12:10:00 UTC] Slack message in #general from U99999: Thread reply",
    }
)

# --- Hermes Telegram fixtures ---

_HERMES_TELEGRAM_DM_KEY = "agent:main:telegram:dm:123456"
_HERMES_TELEGRAM_GROUP_KEY = "agent:main:telegram:group:789012"

_HERMES_TELEGRAM_SESSIONS_JSON = json.dumps(
    {
        _HERMES_TELEGRAM_DM_KEY: {
            "session_id": "tg-dm-uuid",
            "chat_type": "dm",
            "origin": {"chat_id": "123456"},
        },
        _HERMES_TELEGRAM_GROUP_KEY: {
            "session_id": "tg-group-uuid",
            "chat_type": "group",
            "origin": {"chat_id": "789012"},
        },
    }
)

# --- OpenClaw Telegram fixtures ---

_TELEGRAM_CHANNEL_SESSION_KEY = "agent:main:telegram:channel:tg_chat_123"
_TELEGRAM_DM_SESSION_KEY = "agent:main:telegram:dm:user42"

_TELEGRAM_DM_INBOUND_LINE = json.dumps(
    {
        "id": "tg-dm-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 15:00:00 UTC] Telegram message in DM from user42: Hello via DM!",
    }
)

_TELEGRAM_DM_OUTBOUND_LINE = json.dumps(
    {
        "id": "tg-dm-002",
        "type": "message",
        "timestamp": "2025-05-01T15:00:05Z",
        "message": {
            "role": "assistant",
            "model": "delivery-mirror",
            "content": [{"type": "text", "text": "DM reply from bot!"}],
        },
    }
)

_TELEGRAM_DM_SESSIONS_JSON = json.dumps(
    {
        _TELEGRAM_DM_SESSION_KEY: {
            "sessionId": "tg-dm-uuid",
            "chatType": "dm",
            "groupId": "user42",
            "origin": {"nativeChannelId": "USER42", "threadId": None},
        },
    }
)

_TELEGRAM_INBOUND_LINE = json.dumps(
    {
        "id": "tg-msg-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 14:00:00 UTC] Telegram message in MyGroup from user42: Hello from Telegram!",
    }
)

_TELEGRAM_OUTBOUND_LINE = json.dumps(
    {
        "id": "tg-msg-002",
        "type": "message",
        "timestamp": "2025-05-01T14:00:05Z",
        "message": {
            "role": "assistant",
            "model": "delivery-mirror",
            "content": [{"type": "text", "text": "Hi from the bot on Telegram!"}],
        },
    }
)

_TELEGRAM_SESSIONS_JSON = json.dumps(
    {
        _TELEGRAM_CHANNEL_SESSION_KEY: {
            "sessionId": "tgtg-uuid",
            "chatType": "channel",
            "groupId": "tg_chat_123",
            "origin": {"nativeChannelId": "TG_CHAT_123", "threadId": None},
        },
    }
)


def _make_get_jsonl(mapping: dict[str, str]):
    def get_jsonl(session_uuid: str) -> str:
        return mapping.get(session_uuid, "")

    return get_jsonl


def test_parse_sessions_extracts_inbound_message():
    messages = parse_sessions(
        _AGENT_ID,
        _SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": _CHANNEL_JSONL, "cccc-dddd": ""}),
    )

    inbound = [m for m in messages if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1
    assert inbound[0].content == "Hello agent!"
    assert inbound[0].sender_id == "U12345"
    assert inbound[0].channel_name == "general"
    assert inbound[0].channel_id == "C0B4W57JVEZ"
    assert inbound[0].thread_id is None
    assert inbound[0].openclaw_msg_id == "msg-001"
    assert inbound[0].agent_id == _AGENT_ID


def test_parse_sessions_extracts_outbound_message():
    messages = parse_sessions(
        _AGENT_ID,
        _SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": _CHANNEL_JSONL, "cccc-dddd": ""}),
    )

    outbound = [m for m in messages if m.direction == MessageDirection.OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].content == "Hello! How can I help?"
    assert outbound[0].sender_id is None
    assert outbound[0].openclaw_msg_id == "msg-002"


def test_parse_sessions_skips_non_delivery_mirror_outbound():
    messages = parse_sessions(
        _AGENT_ID,
        _SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": _CHANNEL_JSONL, "cccc-dddd": ""}),
    )

    msg_ids = {m.openclaw_msg_id for m in messages}
    assert "msg-003" not in msg_ids


def test_parse_sessions_thread_messages_have_thread_id():
    messages = parse_sessions(
        _AGENT_ID,
        _SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": "", "cccc-dddd": _THREAD_JSONL}),
    )

    assert len(messages) == 1
    assert messages[0].thread_id == "1779269814.824809"
    assert messages[0].channel_id == "C0B4W57JVEZ"
    assert messages[0].session_key == _THREAD_SESSION_KEY


def test_parse_sessions_skips_non_slack_sessions():
    sessions_with_extra = json.dumps(
        {
            "agent:main:other:channel:xyz": {
                "sessionId": "eeee-ffff",
                "origin": {"nativeChannelId": "CXYZ"},
            },
            _CHANNEL_SESSION_KEY: {
                "sessionId": "aaaa-bbbb",
                "origin": {"nativeChannelId": "C0B4W57JVEZ", "threadId": None},
            },
        }
    )

    called = []

    def get_jsonl(session_uuid: str) -> str:
        called.append(session_uuid)
        return _INBOUND_LINE

    parse_sessions(_AGENT_ID, sessions_with_extra, get_jsonl)
    assert "eeee-ffff" not in called
    assert "aaaa-bbbb" in called


def test_parse_sessions_handles_invalid_sessions_json():
    messages = parse_sessions(_AGENT_ID, "not json", lambda _: "")
    assert messages == []


def test_parse_sessions_skips_session_if_jsonl_fetch_fails():
    def failing_get_jsonl(session_uuid: str) -> str:
        raise RuntimeError("pod exec failed")

    messages = parse_sessions(_AGENT_ID, _SESSIONS_JSON, failing_get_jsonl)
    assert messages == []


_DM_SESSION_KEY = "agent:main:main"
_DM_NATIVE_CHANNEL_ID = "D0B5TKTRH8Q"

_DM_SESSIONS_JSON = json.dumps(
    {
        _CHANNEL_SESSION_KEY: {
            "sessionId": "aaaa-bbbb",
            "chatType": "channel",
            "groupId": "c0b4w57jvez",
            "origin": {"nativeChannelId": "C0B4W57JVEZ", "threadId": None},
        },
        _DM_SESSION_KEY: {
            "sessionId": "dddd-eeee",
            "chatType": "direct",
            "origin": {
                "provider": "slack",
                "chatType": "direct",
                "nativeChannelId": _DM_NATIVE_CHANNEL_ID,
                "from": "slack:U0B4ZA25F5Y",
                "sender": "samuel",
            },
        },
    }
)

_DM_CUSTOM_MESSAGE = json.dumps(
    {
        "id": "cm-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": (
            "System (untrusted): [2026-05-25 08:11:30 UTC] Slack DM from samuel: Hello! Are you there?\n"
            "System (untrusted): [2026-05-25 08:20:45 UTC] Slack DM from samuel: Hi buddy\n"
            "\n"
            "Conversation info (untrusted metadata):\n"
            '{"chat_id":"user:U0B4ZA25F5Y","message_id":"mid-001","sender_id":"U0B4ZA25F5Y","sender":"samuel"}'
        ),
    }
)

_DM_OUTBOUND_LINE = json.dumps(
    {
        "id": "out-001",
        "type": "message",
        "timestamp": "2026-05-25T08:23:32.288Z",
        "message": {
            "role": "assistant",
            "model": "gpt-5-mini",
            "content": [{"type": "text", "text": "Hey Sam, I'm here!"}],
        },
    }
)

_DM_JSONL = f"{_DM_CUSTOM_MESSAGE}\n{_DM_OUTBOUND_LINE}"


def test_dm_parse_inbound_messages():
    messages = parse_sessions(
        _AGENT_ID,
        _DM_SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": "", "dddd-eeee": _DM_JSONL}),
    )

    inbound = [
        m for m in messages if m.direction == MessageDirection.INBOUND and m.conversation_type == ConversationType.DM
    ]
    assert len(inbound) == 2
    assert inbound[0].content == "Hello! Are you there?"
    assert inbound[0].sender_name == "samuel"
    assert inbound[0].sender_id == "U0B4ZA25F5Y"
    assert inbound[0].channel_id == _DM_NATIVE_CHANNEL_ID
    assert inbound[0].thread_id is None
    assert inbound[1].content == "Hi buddy"


def test_dm_parse_outbound_message():
    messages = parse_sessions(
        _AGENT_ID,
        _DM_SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": "", "dddd-eeee": _DM_JSONL}),
    )

    outbound = [
        m for m in messages if m.direction == MessageDirection.OUTBOUND and m.conversation_type == ConversationType.DM
    ]
    assert len(outbound) == 1
    assert outbound[0].content == "Hey Sam, I'm here!"
    assert outbound[0].openclaw_msg_id == "out-001"
    assert outbound[0].channel_id == _DM_NATIVE_CHANNEL_ID


def test_dm_inbound_msg_ids_are_stable():
    messages = parse_sessions(
        _AGENT_ID,
        _DM_SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": "", "dddd-eeee": _DM_JSONL}),
    )

    inbound = [
        m for m in messages if m.direction == MessageDirection.INBOUND and m.conversation_type == ConversationType.DM
    ]
    assert inbound[0].openclaw_msg_id == f"dm:{_DM_NATIVE_CHANNEL_ID}:2026-05-25 08:11:30 UTC"
    assert inbound[1].openclaw_msg_id == f"dm:{_DM_NATIVE_CHANNEL_ID}:2026-05-25 08:20:45 UTC"


def test_dm_session_does_not_affect_channel_messages():
    messages = parse_sessions(
        _AGENT_ID,
        _DM_SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": _CHANNEL_JSONL, "dddd-eeee": _DM_JSONL}),
    )

    channel_msgs = [m for m in messages if m.conversation_type == ConversationType.CHANNEL]
    dm_msgs = [m for m in messages if m.conversation_type == ConversationType.DM]
    assert len(channel_msgs) == 2  # 1 inbound + 1 outbound from channel
    assert len(dm_msgs) == 3  # 2 inbound + 1 outbound from DM


def test_dm_session_skipped_if_not_direct():
    sessions = json.loads(_DM_SESSIONS_JSON)
    sessions[_DM_SESSION_KEY]["chatType"] = "channel"
    called = []

    def get_jsonl(uuid: str) -> str:
        called.append(uuid)
        return ""

    parse_sessions(_AGENT_ID, json.dumps(sessions), get_jsonl)
    assert "dddd-eeee" not in called


def test_dm_session_skipped_if_not_slack_provider():
    sessions = json.loads(_DM_SESSIONS_JSON)
    sessions[_DM_SESSION_KEY]["origin"]["provider"] = "teams"
    called = []

    def get_jsonl(uuid: str) -> str:
        called.append(uuid)
        return ""

    parse_sessions(_AGENT_ID, json.dumps(sessions), get_jsonl)
    assert "dddd-eeee" not in called


def test_parse_sessions_skips_lines_with_missing_id():
    line_no_id = json.dumps(
        {
            "type": "custom_message",
            "customType": "openclaw.runtime-context",
            "content": "[2025-05-01 12:00:00 UTC] Slack message in #general from U12345: Hi",
        }
    )
    messages = parse_sessions(
        _AGENT_ID,
        _SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": line_no_id, "cccc-dddd": ""}),
    )
    assert messages == []


# --- Teams parser tests ---

_TEAMS_CHANNEL_SESSION_KEY = "agent:main:msteams:channel:conv123"
_TEAMS_GROUP_SESSION_KEY = "agent:main:msteams:group:group456"

_TEAMS_SESSIONS_JSON = json.dumps(
    {
        _TEAMS_CHANNEL_SESSION_KEY: {
            "sessionId": "tttt-uuuu",
            "chatType": "channel",
            "groupId": "conv123",
            "origin": {"nativeChannelId": "CONV123", "threadId": None},
        },
        _TEAMS_GROUP_SESSION_KEY: {
            "sessionId": "vvvv-wwww",
            "groupId": "group456",
            "origin": {"nativeChannelId": "GROUP456", "threadId": None},
        },
    }
)

_TEAMS_INBOUND_LINE = json.dumps(
    {
        "id": "teams-msg-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 14:00:00 UTC] Teams message in General from user@tenant: Hello from Teams!",
    }
)

_TEAMS_OUTBOUND_LINE = json.dumps(
    {
        "id": "teams-msg-002",
        "type": "message",
        "timestamp": "2025-05-01T14:00:05Z",
        "message": {
            "role": "assistant",
            "model": "delivery-mirror",
            "content": [{"type": "text", "text": "Hi from the bot!"}],
        },
    }
)


def test_parses_teams_inbound_message():
    messages = parse_sessions(
        _AGENT_ID,
        _TEAMS_SESSIONS_JSON,
        _make_get_jsonl({"tttt-uuuu": _TEAMS_INBOUND_LINE, "vvvv-wwww": ""}),
    )

    inbound = [m for m in messages if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1
    assert inbound[0].content == "Hello from Teams!"
    assert inbound[0].sender_id == "user@tenant"
    assert inbound[0].channel_id == "CONV123"
    assert inbound[0].openclaw_msg_id == "teams-msg-001"


def test_parses_teams_outbound_message():
    messages = parse_sessions(
        _AGENT_ID,
        _TEAMS_SESSIONS_JSON,
        _make_get_jsonl(
            {
                "tttt-uuuu": f"{_TEAMS_INBOUND_LINE}\n{_TEAMS_OUTBOUND_LINE}",
                "vvvv-wwww": "",
            }
        ),
    )

    outbound = [m for m in messages if m.direction == MessageDirection.OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].content == "Hi from the bot!"
    assert outbound[0].openclaw_msg_id == "teams-msg-002"


def test_skips_non_msteams_non_slack_sessions():
    sessions_with_unknown = json.dumps(
        {
            "agent:main:discord:channel:xyz": {
                "sessionId": "xxxx-yyyy",
                "origin": {"nativeChannelId": "CXYZ"},
            },
            _TEAMS_CHANNEL_SESSION_KEY: {
                "sessionId": "tttt-uuuu",
                "origin": {"nativeChannelId": "CONV123", "threadId": None},
            },
        }
    )

    called = []

    def get_jsonl(session_uuid: str) -> str:
        called.append(session_uuid)
        return _TEAMS_INBOUND_LINE

    parse_sessions(_AGENT_ID, sessions_with_unknown, get_jsonl)
    assert "xxxx-yyyy" not in called
    assert "tttt-uuuu" in called


# --- Thread de-fragmentation tests ---

# One Slack thread (root 1779951815.019809) that openclaw split across three
# sessions because the agent replied with non-root threadIds:
#   - root session: holds inbound runtime-context (message_id -> topic_id) and
#     the outbound toolCall/toolResult pairs that reveal posted message ts.
#   - poke session: threadId 1779951866.292209 (== an inbound message_id).
#   - bump session: threadId 1779951960.995039 (== a posted message ts).
_ROOT = "1779951815.019809"
_FRAG_CHANNEL = "C0B4ZA29S0J"

_FRAG_ROOT_KEY = f"agent:main:slack:channel:c0b4za29s0j:thread:{_ROOT}"
_FRAG_POKE_KEY = "agent:main:slack:channel:c0b4za29s0j:thread:1779951866.292209"
_FRAG_BUMP_KEY = "agent:main:slack:channel:c0b4za29s0j:thread:1779951960.995039"

_FRAG_SESSIONS_JSON = json.dumps(
    {
        _FRAG_ROOT_KEY: {
            "sessionId": "root-uuid",
            "chatType": "channel",
            "groupId": "c0b4za29s0j",
            "origin": {"nativeChannelId": _FRAG_CHANNEL, "threadId": _ROOT},
        },
        _FRAG_POKE_KEY: {
            "sessionId": "poke-uuid",
            "chatType": "channel",
            "groupId": "c0b4za29s0j",
            "origin": {"threadId": "1779951866.292209"},
        },
        _FRAG_BUMP_KEY: {
            "sessionId": "bump-uuid",
            "chatType": "channel",
            "groupId": "c0b4za29s0j",
            "origin": {"threadId": "1779951960.995039"},
        },
    }
)


def _frag_inbound(message_id: str, ts_str: str, text: str, root: str = _ROOT) -> str:
    return json.dumps(
        {
            "id": f"in-{message_id}",
            "type": "custom_message",
            "customType": "openclaw.runtime-context",
            "content": (
                f"System (untrusted): [{ts_str}] Slack message in #social from samuel: {text}\n\n"
                "Conversation info (untrusted metadata):\n"
                "```json\n"
                + json.dumps(
                    {
                        "message_id": message_id,
                        "reply_to_id": root,
                        "topic_id": root,
                    }
                )
                + "\n```"
            ),
        }
    )


def _frag_toolcall(call_id: str, thread_id: str, text: str) -> str:
    return json.dumps(
        {
            "id": f"tc-{call_id}",
            "type": "message",
            "timestamp": "2026-05-28T07:04:08.732Z",
            "message": {
                "role": "assistant",
                "model": "gpt-5-mini",
                "content": [
                    {
                        "type": "toolCall",
                        "id": call_id,
                        "name": "message",
                        "arguments": {
                            "action": "send",
                            "channel": "slack",
                            "threadId": thread_id,
                            "message": text,
                        },
                    }
                ],
            },
        }
    )


def _frag_toolresult(call_id: str, posted_id: str) -> str:
    return json.dumps(
        {
            "id": f"tr-{call_id}",
            "type": "message",
            "timestamp": "2026-05-28T07:04:09.271Z",
            "message": {
                "role": "toolResult",
                "toolCallId": call_id,
                "toolName": "message",
                "details": {"ok": True, "result": {"messageId": posted_id}},
            },
        }
    )


def _frag_delivery(msg_id: str, ts: str, text: str) -> str:
    return json.dumps(
        {
            "id": msg_id,
            "type": "message",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "model": "delivery-mirror",
                "content": [{"type": "text", "text": text}],
            },
        }
    )


# Root session: inbound metadata + the tool call/result pairs that link the
# fragmented threadIds back to the root.
_FRAG_ROOT_JSONL = "\n".join(
    [
        _frag_inbound(_ROOT, "2026-05-28 07:03:41 UTC", "hey aria"),
        _frag_delivery("d-hey", "2026-05-28T07:04:09.237Z", "Hey Samuel!"),
        _frag_inbound("1779951866.292209", "2026-05-28 07:04:28 UTC", "let's talk sth fun"),
        _frag_delivery("d-love", "2026-05-28T07:04:54.355Z", "Love that"),
        # poke posted with threadId == the "let's talk" inbound message id
        _frag_toolcall("call-poke", "1779951866.292209", "(poke) Any pick?"),
        _frag_toolresult("call-poke", "1779951902.283469"),
        # quick-one posted to the root, Slack assigns ts 1779951960.995039
        _frag_toolcall("call-quick", _ROOT, "Quick one"),
        _frag_toolresult("call-quick", "1779951960.995039"),
        # bump posted with threadId == the quick-one post ts
        _frag_toolcall("call-bump", "1779951960.995039", "If anyone else"),
        _frag_toolresult("call-bump", "1779951969.812249"),
    ]
)
_FRAG_POKE_JSONL = _frag_delivery("d-poke", "2026-05-28T07:05:02.601Z", "(poke) Any pick?")
_FRAG_BUMP_JSONL = _frag_delivery("d-bump", "2026-05-28T07:06:10.202Z", "If anyone else")


def test_fragmented_thread_collapses_to_single_root():
    messages = parse_sessions(
        _AGENT_ID,
        _FRAG_SESSIONS_JSON,
        _make_get_jsonl(
            {
                "root-uuid": _FRAG_ROOT_JSONL,
                "poke-uuid": _FRAG_POKE_JSONL,
                "bump-uuid": _FRAG_BUMP_JSONL,
            }
        ),
    )

    assert messages, "expected parsed messages"
    thread_ids = {m.thread_id for m in messages}
    assert thread_ids == {_ROOT}, f"all messages should resolve to the root thread, got {thread_ids}"


def test_distinct_real_threads_are_not_merged():
    """A genuinely separate thread (different topic_id) must stay separate."""
    other_root = "1779999999.000001"
    other_key = f"agent:main:slack:channel:c0b4za29s0j:thread:{other_root}"
    sessions = json.loads(_FRAG_SESSIONS_JSON)
    sessions[other_key] = {
        "sessionId": "other-uuid",
        "chatType": "channel",
        "groupId": "c0b4za29s0j",
        "origin": {"nativeChannelId": _FRAG_CHANNEL, "threadId": other_root},
    }
    other_jsonl = _frag_inbound(other_root, "2026-05-28 09:00:00 UTC", "new topic", root=other_root)

    messages = parse_sessions(
        _AGENT_ID,
        json.dumps(sessions),
        _make_get_jsonl(
            {
                "root-uuid": _FRAG_ROOT_JSONL,
                "poke-uuid": _FRAG_POKE_JSONL,
                "bump-uuid": _FRAG_BUMP_JSONL,
                "other-uuid": other_jsonl,
            }
        ),
    )

    thread_ids = {m.thread_id for m in messages}
    assert thread_ids == {_ROOT, other_root}, f"distinct threads must remain separate, got {thread_ids}"


def test_handles_both_slack_and_teams_sessions():
    mixed_sessions = json.dumps(
        {
            _CHANNEL_SESSION_KEY: {
                "sessionId": "aaaa-bbbb",
                "origin": {"nativeChannelId": "C0B4W57JVEZ", "threadId": None},
            },
            _TEAMS_CHANNEL_SESSION_KEY: {
                "sessionId": "tttt-uuuu",
                "origin": {"nativeChannelId": "CONV123", "threadId": None},
            },
        }
    )

    messages = parse_sessions(
        _AGENT_ID,
        mixed_sessions,
        _make_get_jsonl({"aaaa-bbbb": _INBOUND_LINE, "tttt-uuuu": _TEAMS_INBOUND_LINE}),
    )

    assert len(messages) == 2
    contents = {m.content for m in messages}
    assert "Hello agent!" in contents
    assert "Hello from Teams!" in contents


# --- Hermes parser: Telegram session prefix tests ---


def test_hermes_distinct_conversations_telegram_dm():
    convos = hermes_distinct_conversations(_HERMES_TELEGRAM_SESSIONS_JSON)
    dm_convos = [(cid, ct, name) for cid, ct, name in convos if ct == ConversationType.DM]
    assert len(dm_convos) == 1
    assert dm_convos[0][0] == "123456"


def test_hermes_distinct_conversations_telegram_group():
    convos = hermes_distinct_conversations(_HERMES_TELEGRAM_SESSIONS_JSON)
    group_convos = [(cid, ct, name) for cid, ct, name in convos if ct == ConversationType.CHANNEL]
    assert len(group_convos) == 1
    assert group_convos[0][0] == "789012"


def test_hermes_channel_sessions_telegram():
    sessions = hermes_channel_sessions(_HERMES_TELEGRAM_SESSIONS_JSON, "789012")
    assert len(sessions) == 1
    assert sessions[0][0] == _HERMES_TELEGRAM_GROUP_KEY
    assert sessions[0][1] == "tg-group-uuid"


# --- OpenClaw parser: Telegram session prefix tests ---


def test_openclaw_parser_telegram_session_prefix():
    messages = parse_sessions(
        _AGENT_ID,
        _TELEGRAM_SESSIONS_JSON,
        _make_get_jsonl({"tgtg-uuid": f"{_TELEGRAM_INBOUND_LINE}\n{_TELEGRAM_OUTBOUND_LINE}"}),
    )

    outbound = [m for m in messages if m.direction == MessageDirection.OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].content == "Hi from the bot on Telegram!"
    assert outbound[0].channel_id == "TG_CHAT_123"


def test_openclaw_parser_telegram_dm_session_prefix():
    messages = parse_sessions(
        _AGENT_ID,
        _TELEGRAM_DM_SESSIONS_JSON,
        _make_get_jsonl({"tg-dm-uuid": f"{_TELEGRAM_DM_INBOUND_LINE}\n{_TELEGRAM_DM_OUTBOUND_LINE}"}),
    )

    assert len(messages) == 2
    inbound = [m for m in messages if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1
    assert inbound[0].content == "Hello via DM!"
    assert inbound[0].sender_id == "user42"
    outbound = [m for m in messages if m.direction == MessageDirection.OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].content == "DM reply from bot!"
    assert outbound[0].channel_id == "USER42"
