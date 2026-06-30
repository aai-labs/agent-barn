import json
import os
import types
from unittest.mock import MagicMock, patch

from hamcrest import assert_that, equal_to, has_length, is_

from api.tests.core.givenpy import given, then, when

_ENV = {
    "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "INGEST_URL": "http://localhost:8001/ingest/v1",
    "INGEST_API_KEY": "test-key-123",
}


def _load_plugin():
    import importlib.util

    path = (
        os.path.dirname(__file__)
        + "/../../domains/agents/scripts/hermes/plugins/telemetry-push/__init__.py"
    )
    spec = importlib.util.spec_from_file_location(
        "telemetry_push", os.path.abspath(path)
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_event(
    text="hello", chat_type="dm", chat_id="C123", user_id="U456", message_id=None
):
    source = types.SimpleNamespace(
        platform="slack",
        chat_type=chat_type,
        chat_id=chat_id,
        user_id=user_id,
    )
    return types.SimpleNamespace(
        text=text,
        source=source,
        message_id=message_id,
    )


def _register(mod):
    hooks = {}
    ctx = MagicMock()
    ctx.register_hook.side_effect = lambda name, fn: hooks.update({name: fn})
    mod.register(ctx)
    return hooks, ctx


# --- register ---


def test_register_returns_early_without_env_vars():
    with given():
        with when("I register the plugin without env vars"):
            with patch.dict(os.environ, {}, clear=True):
                mod = _load_plugin()
                ctx = MagicMock()
                mod.register(ctx)

        with then("no hooks are registered"):
            ctx.register_hook.assert_not_called()


def test_register_hooks_with_env_vars():
    with given():
        with when("I register the plugin with valid env vars"):
            with patch.dict(os.environ, _ENV, clear=True):
                mod = _load_plugin()
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
            mod = _load_plugin()

        with when("I build a session key for a DM"):
            key = mod._build_session_key("dm", "D999")

        with then("the key uses the dm prefix"):
            assert_that(key, equal_to("agent:main:slack:dm:D999"))


def test_channel_session_key():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()

        with when("I build a session key for a channel"):
            key = mod._build_session_key("channel", "C123")

        with then("the key uses the group prefix"):
            assert_that(key, equal_to("agent:main:slack:group:C123"))


def test_group_session_key():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()

        with when("I build a session key for a group"):
            key = mod._build_session_key("group", "G456")

        with then("the key uses the group prefix"):
            assert_that(key, equal_to("agent:main:slack:group:G456"))


# --- buffer ---


def test_pre_gateway_dispatch_buffers_inbound_message():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()
            hooks, _ = _register(mod)
        event = _make_event(
            text="hello", chat_type="dm", chat_id="C123", user_id="U456"
        )

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
            mod = _load_plugin()
            hooks, _ = _register(mod)

        with when("a post_llm_call fires with an assistant response"):
            hooks["post_llm_call"](
                session_id="sess-1",
                user_message="hi",
                assistant_response="hello back",
                conversation_history=[],
                model="qwen3",
                platform="slack",
            )

        with then("an outbound message is buffered"):
            outbound = [
                e
                for e in mod._buffer
                if e["type"] == "message" and e["data"]["direction"] == "OUTBOUND"
            ]
            assert_that(outbound, has_length(1))
            assert_that(outbound[0]["data"]["content"], equal_to("hello back"))


def test_pre_tool_call_buffers_tool_call():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()
            hooks, _ = _register(mod)

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
            mod = _load_plugin()
            hooks, _ = _register(mod)
        hooks["pre_tool_call"](
            tool_name="terminal", args={"command": "ls"}, task_id="task-1"
        )

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
            mod = _load_plugin()
            hooks, _ = _register(mod)
        event = _make_event(
            text="test msg", chat_type="dm", chat_id="C123", user_id="U456"
        )
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
            mod = _load_plugin()
            hooks, _ = _register(mod)
        hooks["pre_gateway_dispatch"](_make_event())
        assert_that(mod._buffer, has_length(1))

        with when("I flush the buffer"):
            mod._flush()

        with then("the buffer is empty"):
            assert_that(mod._buffer, has_length(0))


@patch("urllib.request.urlopen", side_effect=Exception("network error"))
def test_flush_does_not_crash_on_http_error(mock_urlopen):
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()
            hooks, _ = _register(mod)
        hooks["pre_gateway_dispatch"](_make_event())

        with when("I flush and the HTTP call fails"):
            mod._flush()

        with then("no exception propagates"):
            pass


def test_empty_flush_is_noop():
    with given():
        with patch.dict(os.environ, _ENV, clear=True):
            mod = _load_plugin()

        with when("I flush an empty buffer"):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mod._flush()

        with then("no HTTP request is made"):
            mock_urlopen.assert_not_called()
