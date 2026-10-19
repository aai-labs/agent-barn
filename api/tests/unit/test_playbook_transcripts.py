from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, contains_exactly, contains_string, ends_with, equal_to, is_not, less_than_or_equal_to

from api.domains.conversations.models import MessageDirection
from api.domains.playbooks.transcripts import (
    SESSION_CHARS,
    ConversationSpan,
    MessageRow,
    ToolCallRow,
    ToolSessionSpan,
    assign_tool_sessions,
    estimated_tokens,
    render_transcripts,
)

T0 = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _conversation(key: str, start: int, end: int) -> ConversationSpan:
    return ConversationSpan(session_key=key, started_at=_at(start), ended_at=_at(end))


def _tools(session_id: str, start: int, end: int) -> ToolSessionSpan:
    return ToolSessionSpan(session_id=session_id, started_at=_at(start), ended_at=_at(end))


def _message(key: str, at: int, content: str, direction=MessageDirection.INBOUND, sender: str | None = "Ana"):
    return MessageRow(session_key=key, direction=direction, sender_name=sender, content=content, occurred_at=_at(at))


def _call(session_id: str, at: int, tool: str = "exec", arguments=None, result="ok") -> ToolCallRow:
    return ToolCallRow(
        session_id=session_id,
        tool_name=tool,
        arguments=arguments if arguments is not None else {"command": "ls"},
        result=result,
        status="SUCCESS",
        occurred_at=_at(at),
    )


def test_a_runtime_session_inside_a_conversation_belongs_to_it():
    owners = assign_tool_sessions([_conversation("thread-a", 0, 120)], [_tools("run-1", 10, 110)])

    assert_that(owners, equal_to({"run-1": "thread-a"}))


def test_a_runtime_session_may_start_and_end_just_outside_the_mirrored_messages():
    owners = assign_tool_sessions([_conversation("thread-a", 0, 60)], [_tools("run-1", -20, 85)])

    assert_that(owners, equal_to({"run-1": "thread-a"}))


def test_overlapping_conversations_take_the_runtime_sessions_that_fit_them_most_closely():
    web_chat = _conversation("web-chat", 0, 56)
    slack = _conversation("slack-thread", 7, 110)

    owners = assign_tool_sessions([web_chat, slack], [_tools("inside-both", 11, 48), _tools("slack-only", 12, 105)])

    assert_that(owners, equal_to({"inside-both": "web-chat", "slack-only": "slack-thread"}))


def test_runtime_sessions_outside_every_conversation_are_left_out():
    owners = assign_tool_sessions([_conversation("thread-a", 0, 60)], [_tools("startup", 600, 640)])

    assert_that(owners, equal_to({}))


def test_a_transcript_interleaves_messages_and_tool_calls_in_time_order():
    [transcript] = render_transcripts(
        [_conversation("thread-a", 0, 30)],
        [
            _message("thread-a", 0, "Please summarise the open invoices"),
            _message("thread-a", 30, "Three invoices are open.", MessageDirection.OUTBOUND),
        ],
        [_call("run-1", 10, "exec", {"command": "aai-cli invoices list"}, "3 rows")],
        {"run-1": "thread-a"},
    )

    lines = transcript.text.splitlines()
    assert_that(
        lines,
        contains_exactly(
            "Conversation from 2026-09-30 08:00 UTC",
            "[08:00:00] Person (Ana): Please summarise the open invoices",
            "[08:00:10] Tool exec (success)",
            '  arguments: {"command": "aai-cli invoices list"}',
            "  result: 3 rows",
            "[08:00:30] Agent: Three invoices are open.",
        ),
    )
    assert_that((transcript.message_count, transcript.tool_call_count), equal_to((2, 1)))


def test_tool_calls_of_unpaired_runtime_sessions_are_not_rendered():
    [transcript] = render_transcripts(
        [_conversation("thread-a", 0, 30)],
        [_message("thread-a", 0, "Hello")],
        [_call("startup", 5, "read")],
        {},
    )

    assert_that(transcript.text, is_not(contains_string("Tool read")))
    assert_that(transcript.tool_call_count, equal_to(0))


def test_long_tool_output_is_clipped_with_the_amount_left_out():
    [transcript] = render_transcripts(
        [_conversation("thread-a", 0, 30)],
        [],
        [_call("run-1", 1, result="x" * 2_000)],
        {"run-1": "thread-a"},
    )

    assert_that(transcript.text, contains_string("x" * 1_500 + " [… 500 more characters]"))


def test_an_oversized_session_is_compacted_then_capped():
    calls = [_call("run-1", i, result="y" * 1_500, arguments={"q": "z" * 1_000}) for i in range(200)]

    [transcript] = render_transcripts(
        [_conversation("thread-a", 0, 300)], [_message("thread-a", 0, "Go")], calls, {"run-1": "thread-a"}
    )

    assert_that(transcript.text, contains_string("Person (Ana): Go"))
    assert_that(transcript.text, contains_string("y" * 300 + " [… 1200 more characters]"))
    assert_that(transcript.text, ends_with("[transcript truncated]"))
    assert_that(len(transcript.text), less_than_or_equal_to(SESSION_CHARS + len("\n[transcript truncated]")))


def test_token_estimates_round_up_from_characters():
    assert_that([estimated_tokens(0), estimated_tokens(1), estimated_tokens(8)], contains_exactly(0, 1, 2))
