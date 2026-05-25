"""Unit tests for the conversation JSONL parser — no I/O, no DB, no k8s."""

import json
from uuid import UUID

from api.domains.conversations.models import MessageDirection
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
                "tttt-uuuu": "\n".join([_TEAMS_INBOUND_LINE, _TEAMS_OUTBOUND_LINE]),
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
        _make_get_jsonl(
            {"aaaa-bbbb": _INBOUND_LINE, "tttt-uuuu": _TEAMS_INBOUND_LINE}
        ),
    )

    assert len(messages) == 2
    contents = {m.content for m in messages}
    assert "Hello agent!" in contents
    assert "Hello from Teams!" in contents
