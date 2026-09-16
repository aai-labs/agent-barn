"""Drive agentbarn-observer against Hermes' real gateway state.

Runs inside the pinned Hermes image. The session store, session-key routing,
delivery ledger, and runtime status file are all Hermes' own code, so a runtime
upgrade that renames a state, column, or hook argument fails here.

Exits non-zero with a message when the contract no longer holds.
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

HOME = Path(tempfile.mkdtemp())
os.environ["HERMES_HOME"] = str(HOME)
sys.path.insert(0, "/opt/hermes")

# Only resolvable inside the Hermes image, which is the only place this runs.
from gateway import delivery_ledger  # ty: ignore[unresolved-import]
from gateway.config import GatewayConfig, Platform  # ty: ignore[unresolved-import]
from gateway.run import GatewayRunner  # ty: ignore[unresolved-import]
from gateway.session import SessionSource, SessionStore  # ty: ignore[unresolved-import]
from gateway.status import write_runtime_status  # ty: ignore[unresolved-import]
from hermes_cli.plugins import VALID_HOOKS  # ty: ignore[unresolved-import]


def fail(message):
    raise SystemExit("observer contract broken: " + message)


def load_plugin():
    spec = importlib.util.spec_from_file_location("agentbarn_observer", "/plugin/__init__.py")
    loader = spec.loader if spec else None
    if spec is None or loader is None:
        fail("could not load the plugin")
    mod = importlib.util.module_from_spec(spec)  # ty: ignore[invalid-argument-type]
    loader.exec_module(mod)  # ty: ignore[unresolved-attribute]
    mod.__dict__["threading"] = MagicMock()  # no background loop; the driver polls explicitly
    hooks = {}
    ctx = MagicMock()
    ctx.register_hook.side_effect = lambda name, fn: hooks.update({name: fn})
    mod.register(ctx)
    unknown = set(hooks) - VALID_HOOKS
    if unknown:
        fail(f"hooks not accepted by this Hermes: {sorted(unknown)}")
    return mod, hooks


def stages(mod):
    events = [(e["stage"], e.get("correlation_id")) for e in mod._buffer]
    mod._buffer.clear()
    return events


def main():
    mod, hooks = load_plugin()

    store = SessionStore(HOME / "sessions", GatewayConfig())
    # Bare runner, as Hermes' own tests build it; only session routing is exercised.
    gateway = object.__new__(GatewayRunner)
    gateway.session_store = store
    source = SessionSource(platform=Platform.SLACK, chat_id="C1", chat_type="channel", user_id="U1", thread_id="T1")
    entry = store.get_or_create_session(source)

    event = SimpleNamespace(text="secret text", source=source, message_id="1700000000.000100")
    hooks["pre_gateway_dispatch"](event=event, gateway=gateway, session_store=store)
    hooks["pre_llm_call"](session_id=entry.session_id, platform="slack")
    hooks["post_llm_call"](session_id=entry.session_id, platform="slack", assistant_response="secret reply")
    correlation = "slack:1700000000.000100"
    expected = [
        ("provider_observed", correlation),
        ("agent_claimed", correlation),
        ("model_completed", correlation),
    ]
    if (got := stages(mod)) != expected:
        fail(f"run stages {got}, expected {expected}")

    # Native Discord authorization is entirely Hermes-owned. The observer is
    # telemetry-only and must never introduce a second policy decision.
    discord_source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="D1",
        chat_type="dm",
        user_id="U1",
        message_id="discord-message-1",
    )
    discord_event = SimpleNamespace(text="secret discord text", source=discord_source, message_id="discord-message-1")
    decision = hooks["pre_gateway_dispatch"](event=discord_event, gateway=gateway, session_store=store)
    if decision is not None:
        fail(f"Discord observation unexpectedly changed dispatch: {decision!r}")
    expected = [("provider_observed", "discord:discord-message-1")]
    if (got := stages(mod)) != expected:
        fail(f"Discord policy stages {got}, expected {expected}")

    watermark = [0.0]
    delivery_ledger.record_obligation(
        obligation_id="o1",
        session_key=entry.session_key,
        platform="slack",
        chat_id="C1",
        thread_id="T1",
        content="secret reply",
    )
    delivery_ledger.mark_attempting("o1")
    mod.poll_obligations(HOME / "state.db", watermark)
    delivery_ledger.mark_delivered("o1")
    mod.poll_obligations(HOME / "state.db", watermark)
    expected = [("provider_delivery_attempted", correlation), ("provider_delivered", correlation)]
    if (got := stages(mod)) != expected:
        fail(f"delivery stages {got}, expected {expected}")

    health: dict[str, str] = {}
    write_runtime_status(platform="slack", platform_state="retrying", error_code="ratelimited")
    mod.poll_platform_health(HOME / "gateway_state.json", health)
    mod.poll_platform_health(HOME / "gateway_state.json", health)  # unchanged: no duplicate
    write_runtime_status(platform="slack", platform_state="connected")
    mod.poll_platform_health(HOME / "gateway_state.json", health)
    expected = [("connection_degraded", None), ("connection_connected", None)]
    if (got := stages(mod)) != expected:
        fail(f"health stages {got}, expected {expected}")

    print("hermes observer contract ok")


if __name__ == "__main__":
    main()
