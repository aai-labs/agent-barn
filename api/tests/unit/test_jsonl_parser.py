import datetime
from pathlib import Path

from hamcrest import assert_that, equal_to, has_length

from api.domains.tool_calls.jsonl_parser import parse_jsonl
from api.tests.core.givenpy import given, then, when

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "openclaw_session.jsonl"


def _fixture() -> str:
    return _FIXTURE.read_text()


def test_extracts_four_tool_calls():
    with given():
        with when("I parse the fixture JSONL"):
            calls, _ = parse_jsonl(_fixture(), "session-abc")

        with then("four tool calls are extracted"):
            assert_that(calls, has_length(4))


def test_extracts_three_tool_results():
    with given():
        with when("I parse the fixture JSONL"):
            _, results = parse_jsonl(_fixture(), "session-abc")

        with then("three tool results are extracted (write call is pending)"):
            assert_that(results, has_length(3))


def test_read_call_fields():
    with given():
        with when("I parse the fixture JSONL"):
            calls, _ = parse_jsonl(_fixture(), "session-abc")

        with then("the read call has the correct fields"):
            call = next(c for c in calls if c.external_id == "call_ppiEohyny133JGEiW98cIbdA")
            assert_that(call.tool_name, equal_to("read"))
            assert_that(
                call.arguments,
                equal_to({"path": "/repo/config.yaml", "offset": 1, "limit": 200}),
            )
            assert_that(call.session_id, equal_to("session-abc"))


def test_read_result_fields():
    with given():
        with when("I parse the fixture JSONL"):
            _, results = parse_jsonl(_fixture(), "session-abc")

        with then("the read result has the correct fields"):
            result = next(r for r in results if r.external_id == "call_ppiEohyny133JGEiW98cIbdA")
            assert_that(result.is_error, equal_to(False))
            assert_that(
                result.result,
                equal_to([{"type": "text", "text": "db_host: postgres\ndb_port: 5432\n"}]),
            )


def test_error_result_flagged():
    with given():
        with when("I parse the fixture JSONL"):
            _, results = parse_jsonl(_fixture(), "session-abc")

        with then("the bash error result is flagged"):
            result = next(r for r in results if r.external_id == "call_7nBvLsAqMc1YpZoGjHwRdUfT")
            assert_that(result.is_error, equal_to(True))


def test_pending_call_has_no_result():
    with given():
        with when("I parse the fixture JSONL"):
            calls, results = parse_jsonl(_fixture(), "session-abc")

        with then("the write call appears in calls but has no matching result"):
            pending_id = "call_3fDwHiKe8NpSrTmYuVqXjLbA"
            assert_that(any(c.external_id == pending_id for c in calls), equal_to(True))
            assert_that(any(r.external_id == pending_id for r in results), equal_to(False))


def test_session_id_applied_to_all_calls():
    with given():
        with when("I parse JSONL with a custom session ID"):
            calls, _ = parse_jsonl(_fixture(), "my-session-id")

        with then("all calls carry that session ID"):
            assert_that(all(c.session_id == "my-session-id" for c in calls), equal_to(True))


def test_timestamps_are_utc():
    with given():
        with when("I parse the fixture JSONL"):
            calls, results = parse_jsonl(_fixture(), "s")

        with then("all timestamps are UTC"):
            for call in calls:
                assert_that(call.occurred_at.tzinfo, equal_to(datetime.UTC))
            for result in results:
                assert_that(result.completed_at.tzinfo, equal_to(datetime.UTC))


def test_occurred_at_from_inner_message_timestamp():
    with given():
        with when("I parse the fixture JSONL"):
            calls, _ = parse_jsonl(_fixture(), "s")

        with then("occurred_at is derived from the inner message timestamp in milliseconds"):
            call = next(c for c in calls if c.external_id == "call_ppiEohyny133JGEiW98cIbdA")
            expected = datetime.datetime.fromtimestamp(1748000017.575, tz=datetime.UTC)
            assert_that(call.occurred_at, equal_to(expected))


def test_user_message_skipped():
    with given():
        raw = '{"type":"message","id":"u1","message":{"role":"user","content":[{"type":"text","text":"hello"}],"timestamp":1748000000000}}\n'

        with when("I parse a user message"):
            calls, results = parse_jsonl(raw, "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))


def test_text_only_assistant_message_skipped():
    with given():
        raw = '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"text","text":"Thinking..."}],"timestamp":1748000000000}}\n'

        with when("I parse a text-only assistant message"):
            calls, results = parse_jsonl(raw, "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))


def test_malformed_line_skipped():
    with given():
        with when("I parse a malformed JSON line"):
            calls, results = parse_jsonl("not valid json\n", "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))


def test_blank_lines_skipped():
    with given():
        with when("I parse blank lines"):
            calls, results = parse_jsonl("\n\n\n", "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))


def test_empty_input():
    with given():
        with when("I parse an empty string"):
            calls, results = parse_jsonl("", "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))


def test_assistant_message_with_text_and_tool_call():
    with given():
        raw = (
            '{"type":"message","id":"a1","message":{"role":"assistant","content":'
            '[{"type":"text","text":"doing stuff"},{"type":"toolCall","id":"call_x1","name":"ls","arguments":{}}]'
            ',"timestamp":1748000000000}}\n'
        )

        with when("I parse an assistant message with mixed text and tool call content"):
            calls, _ = parse_jsonl(raw, "s")

        with then("only the tool call item is extracted"):
            assert_that(calls, has_length(1))
            assert_that(calls[0].external_id, equal_to("call_x1"))
            assert_that(calls[0].tool_name, equal_to("ls"))


def test_non_message_type_entry_skipped():
    with given():
        with when("I parse a non-message type entry"):
            calls, results = parse_jsonl('{"type":"system","content":"some system event"}\n', "s")

        with then("nothing is extracted"):
            assert_that(calls, has_length(0))
            assert_that(results, has_length(0))
