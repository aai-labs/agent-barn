"""Drive the telemetry-push plugin against Hermes' real session store.

Runs inside the pinned Hermes image, mounted alongside the plugin — see the
"Plugin contract" step in .github/workflows/hermes-base.yml. Nothing here is
faked: real SessionStore, real session-key generation, real session ids. This
is what keeps the fakes in the unit tests honest, since those can only prove
our own routing logic and never the runtime's behaviour.

Exits non-zero with a message when the contract no longer holds.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, "/opt/hermes")

# Only resolvable inside the Hermes image, which is the only place this runs.
from gateway.config import GatewayConfig, Platform  # ty: ignore[unresolved-import]
from gateway.session import SessionSource, SessionStore  # ty: ignore[unresolved-import]

PLUGIN_PATH = "/plugin/__init__.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("telemetry_push", PLUGIN_PATH)
    loader = spec.loader if spec else None
    if spec is None or loader is None:
        raise SystemExit(f"could not load the plugin from {PLUGIN_PATH}")
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    hooks = {}
    ctx = MagicMock()
    ctx.register_hook.side_effect = lambda name, fn: hooks.update({name: fn})
    mod.register(ctx)
    if not hooks:
        raise SystemExit("plugin registered no hooks; check AGENT_ID/INGEST_URL/INGEST_API_KEY")
    return mod, hooks


def outbound_messages(mod):
    return [e["data"] for e in mod._buffer if e["type"] == "message" and e["data"]["direction"] == "OUTBOUND"]


def main():
    mod, hooks = load_plugin()

    store = SessionStore(Path(tempfile.mkdtemp()), GatewayConfig())
    source_a = SessionSource(platform=Platform.SLACK, chat_id="C_AAA", chat_type="dm", user_id="U1")
    source_b = SessionSource(platform=Platform.SLACK, chat_id="C_BBB", chat_type="dm", user_id="U2")

    entry_a = store.get_or_create_session(source_a)
    entry_b = store.get_or_create_session(source_b)
    if entry_a.session_id == entry_b.session_id:
        raise SystemExit("two chats shared one session id; the store cannot distinguish them")

    for source, text in ((source_a, "from A"), (source_b, "from B")):
        event = SimpleNamespace(text=text, source=source, message_id=None)
        hooks["pre_gateway_dispatch"](event=event, gateway=None, session_store=store)

    # Chat B messaged while chat A's call was in flight; A's reply is still A's.
    hooks["post_llm_call"](
        session_id=entry_a.session_id,
        user_message="hi",
        assistant_response="reply for A",
        conversation_history=[],
        model="qwen3",
        platform="slack",
    )

    replies = outbound_messages(mod)
    if len(replies) != 1:
        raise SystemExit(f"expected exactly one outbound message, got {len(replies)}")
    if replies[0]["channel_id"] != "C_AAA":
        raise SystemExit(f"reply attributed to {replies[0]['channel_id']}, expected C_AAA")

    # An unknown session must be dropped rather than attributed to another chat.
    mod._buffer.clear()
    hooks["post_llm_call"](
        session_id="not-a-session",
        user_message="hi",
        assistant_response="orphan reply",
        conversation_history=[],
        model="qwen3",
        platform="slack",
    )
    if outbound_messages(mod):
        raise SystemExit("an unresolvable reply was recorded instead of dropped")

    print("hermes session store contract ok")


if __name__ == "__main__":
    main()
