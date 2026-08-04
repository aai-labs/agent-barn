"""Harness for driving the runtime telemetry-push plugins in tests.

The plugins ship inside agent images rather than being importable modules, so
they are loaded from their source path and their hooks are called directly.
Assertions belong on the payload a plugin posts, not on its internal buffer.
"""

import importlib.util
import json
import os
import types
from unittest.mock import MagicMock, patch

HERMES_PLUGIN_PATH = (
    os.path.dirname(__file__) + "/../../domains/agents/scripts/hermes/plugins/telemetry-push/__init__.py"
)


def load_hermes_plugin():
    spec = importlib.util.spec_from_file_location("telemetry_push", os.path.abspath(HERMES_PLUGIN_PATH))
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def register_hermes_plugin(mod):
    hooks = {}
    ctx = MagicMock()
    ctx.register_hook.side_effect = lambda name, fn: hooks.update({name: fn})
    mod.register(ctx)
    return hooks, ctx


def make_message_event(text="hello", chat_type="dm", chat_id="C123", user_id="U456", message_id=None):
    source = types.SimpleNamespace(
        platform="slack",
        chat_type=chat_type,
        chat_id=chat_id,
        user_id=user_id,
    )
    return types.SimpleNamespace(text=text, source=source, message_id=message_id)


def make_session_entry(session_id, chat_id, chat_type="dm", thread_id=None):
    origin = types.SimpleNamespace(chat_id=chat_id, thread_id=thread_id, user_id="U456")
    suffix = f":{thread_id}" if thread_id else ""
    return types.SimpleNamespace(
        session_key=f"agent:main:slack:{chat_type}:{chat_id}{suffix}",
        session_id=session_id,
        chat_type=chat_type,
        origin=origin,
    )


def make_session_store(*entries):
    return types.SimpleNamespace(list_sessions=lambda: list(entries))


def dispatch(hooks, event, store):
    return hooks["pre_gateway_dispatch"](event=event, gateway=None, session_store=store)


def post_llm_call(hooks, session_id, response="hello back"):
    return hooks["post_llm_call"](
        session_id=session_id,
        user_message="hi",
        assistant_response=response,
        conversation_history=[],
        model="qwen3",
        platform="slack",
    )


def flush_and_capture(mod):
    with patch("urllib.request.urlopen") as mock_urlopen:
        response = MagicMock()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = response
        mod._flush()
        if not mock_urlopen.called:
            return {"messages": [], "tool_calls": [], "tool_results": []}
        return json.loads(mock_urlopen.call_args[0][0].data)


def outbound_messages(payload):
    return [m for m in payload["messages"] if m["direction"] == "OUTBOUND"]
