import json
import os
from unittest.mock import MagicMock, patch

from hamcrest import assert_that, empty, equal_to, has_length, is_

from api.domains.ingest.models import IngestBatchRequest
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.telemetry_plugins import (
    dispatch,
    flush_and_capture,
    load_hermes_plugin,
    make_message_event,
    make_session_entry,
    make_session_store,
    outbound_messages,
    post_llm_call,
    register_hermes_plugin,
)

_ENV = {
    "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "INGEST_URL": "http://localhost:8001/ingest/v1",
    "INGEST_API_KEY": "test-key-123",
}


# --- register ---


def test_register_returns_early_without_env_vars():
    with given():
        with when("I register the plugin without env vars"), patch.dict(os.environ, {}, clear=True):
            mod = load_hermes_plugin()
            ctx = MagicMock()
            mod.register(ctx)

        with then("no hooks are registered"):
            ctx.register_hook.assert_not_called()


def test_register_hooks_with_env_vars():
    with given():
        with when("I register the plugin with valid env vars"), patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            ctx = MagicMock()
            mod.register(ctx)
            hook_names = [call.args[0] for call in ctx.register_hook.call_args_list]

        with then("all five hooks are registered"):
            assert_that("pre_gateway_dispatch" in hook_names, equal_to(True))
            assert_that("post_llm_call" in hook_names, equal_to(True))
            assert_that("pre_tool_call" in hook_names, equal_to(True))
            assert_that("post_tool_call" in hook_names, equal_to(True))
            assert_that("on_session_end" in hook_names, equal_to(True))


# --- session key ---


def test_dm_session_key():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()

        with when("I build a session key for a DM"):
            key = mod._build_session_key("dm", "D999")

        with then("the key uses the dm prefix"):
            assert_that(key, equal_to("agent:main:slack:dm:D999"))


def test_channel_session_key():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()

        with when("I build a session key for a channel"):
            key = mod._build_session_key("channel", "C123")

        with then("the key uses the group prefix"):
            assert_that(key, equal_to("agent:main:slack:group:C123"))


def test_group_session_key():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()

        with when("I build a session key for a group"):
            key = mod._build_session_key("group", "G456")

        with then("the key uses the group prefix"):
            assert_that(key, equal_to("agent:main:slack:group:G456"))


# --- buffer ---


def test_pre_gateway_dispatch_buffers_inbound_message():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        event = make_message_event(text="hello", chat_type="dm", chat_id="C123", user_id="U456")

        with when("I dispatch an inbound message"):
            result = hooks["pre_gateway_dispatch"](event)

        with then("the message is buffered and the hook does not block"):
            assert_that(result, is_(None))
            assert_that(mod._buffer, has_length(1))
            msg = mod._buffer[0]
            assert_that(msg["type"], equal_to("message"))
            assert_that(msg["data"]["direction"], equal_to("INBOUND"))
            assert_that(msg["data"]["content"], equal_to("hello"))
            assert_that(msg["data"]["sender_id"], equal_to("U456"))
            assert_that(msg["data"]["channel_id"], equal_to("C123"))


def test_post_llm_call_buffers_outbound_message():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(make_session_entry("sess-1", "C123"))
        dispatch(hooks, make_message_event(chat_id="C123"), store)

        with when("a post_llm_call fires with an assistant response"):
            post_llm_call(hooks, "sess-1")

        with then("an outbound message is buffered"):
            outbound = [e for e in mod._buffer if e["type"] == "message" and e["data"]["direction"] == "OUTBOUND"]
            assert_that(outbound, has_length(1))
            assert_that(outbound[0]["data"]["content"], equal_to("hello back"))


def test_pre_tool_call_buffers_tool_call():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)

        with when("a pre_tool_call fires"):
            result = hooks["pre_tool_call"](
                tool_name="terminal",
                args={"command": "ls"},
                task_id="task-1",
            )

        with then("a tool call is buffered and the hook does not block"):
            assert_that(result, is_(None))
            tool_calls = [e for e in mod._buffer if e["type"] == "tool_call"]
            assert_that(tool_calls, has_length(1))
            assert_that(tool_calls[0]["data"]["tool_name"], equal_to("terminal"))


def test_post_tool_call_buffers_tool_result():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        hooks["pre_tool_call"](tool_name="terminal", args={"command": "ls"}, task_id="task-1")

        with when("a post_tool_call fires for the same tool"):
            hooks["post_tool_call"](
                tool_name="terminal",
                args={"command": "ls"},
                result="file1.txt\nfile2.txt",
                task_id="task-1",
                duration_ms=150,
            )

        with then("a tool result is buffered with the correct external_id"):
            results = [e for e in mod._buffer if e["type"] == "tool_result"]
            assert_that(results, has_length(1))
            assert_that(results[0]["data"]["result"], equal_to("file1.txt\nfile2.txt"))


# --- chat attribution ---


def test_outbound_goes_to_its_own_chat_when_another_chat_messaged_meanwhile():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(
            make_session_entry("sess-a", "C_AAA"),
            make_session_entry("sess-b", "C_BBB"),
        )
        dispatch(hooks, make_message_event(text="from A", chat_id="C_AAA"), store)
        dispatch(hooks, make_message_event(text="from B", chat_id="C_BBB"), store)

        with when("chat A's LLM call completes after chat B's message arrived"):
            post_llm_call(hooks, "sess-a", response="reply for A")

        with then("the reply is attributed to chat A, not chat B"):
            outbound = outbound_messages(flush_and_capture(mod))
            assert_that(outbound, has_length(1))
            assert_that(outbound[0]["channel_id"], equal_to("C_AAA"))
            assert_that(outbound[0]["session_key"], equal_to("agent:main:slack:dm:C_AAA"))
            assert_that(outbound[0]["content"], equal_to("reply for A"))


def test_each_concurrent_chat_gets_its_own_reply():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(
            make_session_entry("sess-a", "C_AAA"),
            make_session_entry("sess-b", "C_BBB"),
        )
        dispatch(hooks, make_message_event(chat_id="C_AAA"), store)
        dispatch(hooks, make_message_event(chat_id="C_BBB"), store)

        with when("both chats' LLM calls complete out of arrival order"):
            post_llm_call(hooks, "sess-b", response="reply for B")
            post_llm_call(hooks, "sess-a", response="reply for A")

        with then("each reply carries its own chat"):
            outbound = outbound_messages(flush_and_capture(mod))
            by_channel = {m["channel_id"]: m["content"] for m in outbound}
            assert_that(by_channel, equal_to({"C_BBB": "reply for B", "C_AAA": "reply for A"}))


def test_outbound_is_dropped_when_session_is_unknown():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(make_session_entry("sess-a", "C_AAA"))
        dispatch(hooks, make_message_event(chat_id="C_AAA"), store)

        with when("a post_llm_call fires for a session the store does not know"):
            post_llm_call(hooks, "sess-unknown")

        with then("nothing is recorded rather than guessing a chat"):
            assert_that(outbound_messages(flush_and_capture(mod)), is_(empty()))


def test_outbound_is_dropped_when_session_store_was_never_captured():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)

        with when("a reply fires before any inbound dispatch, e.g. a cron run on a fresh pod"):
            post_llm_call(hooks, "sess-a")

        with then("nothing is recorded and no exception escapes"):
            assert_that(outbound_messages(flush_and_capture(mod)), is_(empty()))


def test_thread_scoped_outbound_keeps_its_thread_suffix():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(
            make_session_entry("sess-t", "C123", chat_type="channel", thread_id="1779269814.824809"),
        )
        dispatch(hooks, make_message_event(chat_type="channel", chat_id="C123"), store)

        with when("the reply for a threaded conversation completes"):
            post_llm_call(hooks, "sess-t")

        with then("thread_id is carried and the session key keeps its thread suffix"):
            outbound = outbound_messages(flush_and_capture(mod))
            assert_that(outbound, has_length(1))
            assert_that(outbound[0]["thread_id"], equal_to("1779269814.824809"))
            assert_that(
                outbound[0]["session_key"],
                equal_to("agent:main:slack:group:C123:1779269814.824809"),
            )
            assert_that(outbound[0]["conversation_type"], equal_to("CHANNEL"))


def test_concurrent_calls_to_the_same_tool_keep_distinct_results():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)

        with when("two calls to the same tool overlap within one task"):
            hooks["pre_tool_call"](
                tool_name="terminal", args={"command": "ls"}, task_id="task-1", tool_call_id="call-1"
            )
            hooks["pre_tool_call"](
                tool_name="terminal", args={"command": "pwd"}, task_id="task-1", tool_call_id="call-2"
            )
            hooks["post_tool_call"](
                tool_name="terminal", args={"command": "pwd"}, result="/root", task_id="task-1", tool_call_id="call-2"
            )
            hooks["post_tool_call"](
                tool_name="terminal", args={"command": "ls"}, result="file1", task_id="task-1", tool_call_id="call-1"
            )

        with then("each result is bound to the external id of its own call"):
            payload = flush_and_capture(mod)
            calls = {c["arguments"]["command"]: c["external_id"] for c in payload["tool_calls"]}
            results = {r["external_id"]: r["result"] for r in payload["tool_results"]}
            assert_that(results[calls["ls"]], equal_to("file1"))
            assert_that(results[calls["pwd"]], equal_to("/root"))


def test_flushed_payload_satisfies_the_ingest_contract():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        store = make_session_store(make_session_entry("sess-a", "C_AAA"))
        dispatch(hooks, make_message_event(chat_id="C_AAA"), store)
        post_llm_call(hooks, "sess-a")
        hooks["pre_tool_call"](tool_name="terminal", args={"command": "ls"}, task_id="t1", tool_call_id="call-1")
        hooks["post_tool_call"](
            tool_name="terminal", args={"command": "ls"}, result="ok", task_id="t1", tool_call_id="call-1"
        )

        with when("the buffered batch is flushed"):
            payload = flush_and_capture(mod)

        with then("Ingest accepts it without coercion errors"):
            batch = IngestBatchRequest.model_validate(payload)
            assert_that(batch.messages, has_length(2))
            assert_that(batch.tool_calls, has_length(1))
            assert_that(batch.tool_results, has_length(1))


# --- flush ---


@patch("urllib.request.urlopen")
def test_flush_sends_correct_payload(mock_urlopen):
    with given():
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        event = make_message_event(text="test msg", chat_type="dm", chat_id="C123", user_id="U456")
        hooks["pre_gateway_dispatch"](event)

        with when("I flush the buffer"):
            mod._flush()

        with then("the payload is sent with correct auth and content"):
            assert_that(mock_urlopen.called, equal_to(True))
            req = mock_urlopen.call_args[0][0]
            assert_that(
                req.get_header("Authorization"),
                equal_to("Bearer test-key-123"),
            )
            body = json.loads(req.data)
            assert_that(body["messages"], has_length(1))
            assert_that(body["messages"][0]["content"], equal_to("test msg"))
            assert_that(mod._buffer, has_length(0))


@patch("urllib.request.urlopen")
def test_flush_clears_buffer_on_success(mock_urlopen):
    with given():
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        hooks["pre_gateway_dispatch"](make_message_event())
        assert_that(mod._buffer, has_length(1))

        with when("I flush the buffer"):
            mod._flush()

        with then("the buffer is empty"):
            assert_that(mod._buffer, has_length(0))


@patch("urllib.request.urlopen", side_effect=Exception("network error"))
def test_flush_does_not_crash_on_http_error(mock_urlopen):
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()
            hooks, _ = register_hermes_plugin(mod)
        hooks["pre_gateway_dispatch"](make_message_event())

        with when("I flush and the HTTP call fails"):
            mod._flush()

        with then("no exception propagates"):
            pass


def test_empty_flush_is_noop():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = load_hermes_plugin()

        with when("I flush an empty buffer"), patch("urllib.request.urlopen") as mock_urlopen:
            mod._flush()

        with then("no HTTP request is made"):
            mock_urlopen.assert_not_called()
