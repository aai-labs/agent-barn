"""Unit tests for the conversation JSONL parser — no I/O, no DB, no k8s."""

import json
from uuid import UUID

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

_CHANNEL_JSONL = "\n".join([_INBOUND_LINE, _OUTBOUND_LINE, _IRRELEVANT_LINE])
_THREAD_JSONL = json.dumps(
    {
        "id": "msg-thread-001",
        "type": "custom_message",
        "customType": "openclaw.runtime-context",
        "content": "[2025-05-01 12:10:00 UTC] Slack message in #general from U99999: Thread reply",
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
            'System (untrusted): [2026-05-25 08:11:30 UTC] Slack DM from samuel: Hello! Are you there?\n'
            'System (untrusted): [2026-05-25 08:20:45 UTC] Slack DM from samuel: Hi buddy\n'
            '\n'
            'Conversation info (untrusted metadata):\n'
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

_DM_JSONL = "\n".join([_DM_CUSTOM_MESSAGE, _DM_OUTBOUND_LINE])


def test_dm_parse_inbound_messages():
    messages = parse_sessions(
        _AGENT_ID,
        _DM_SESSIONS_JSON,
        _make_get_jsonl({"aaaa-bbbb": "", "dddd-eeee": _DM_JSONL}),
    )

    inbound = [
        m for m in messages
        if m.direction == MessageDirection.INBOUND and m.conversation_type == ConversationType.DM
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
        m for m in messages
        if m.direction == MessageDirection.OUTBOUND and m.conversation_type == ConversationType.DM
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
        m for m in messages
        if m.direction == MessageDirection.INBOUND and m.conversation_type == ConversationType.DM
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
