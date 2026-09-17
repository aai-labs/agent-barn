"""Report native gateway Journal stages and dashboard transcripts to the ingest API.

Journal events remain content-free. Transcript messages are sent separately so
the dashboard can render native platform conversations; provider error text
never leaves the pod.

Correlation is the inbound provider message (``<platform>:<message_id>``).
Runs and sends only carry a session, so each is attributed to the latest
inbound message observed on that session key.
"""

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.request
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_SECONDS = 2
_MAX_BUFFER = 500
_MAX_TRACKED = 1_000

# gateway/status.py platform_state values in the pinned image.
_PLATFORM_STAGES = {
    "connecting": "connection_connecting",
    "connected": "connection_connected",
    "retrying": "connection_degraded",
    "paused": "connection_degraded",
    "disconnected": "connection_error",
    "fatal": "connection_error",
}

# gateway/delivery_ledger.py obligation states. "pending" precedes any send.
_OBLIGATION_STAGES = {
    "attempting": "provider_delivery_attempted",
    "delivered": "provider_delivered",
    "failed": "provider_delivery_attempted",
    "abandoned": "dead_lettered",
}

_buffer: list[dict] = []
_messages: list[dict] = []
_lock = threading.Lock()
_latest_inbound: OrderedDict[str, str] = OrderedDict()  # session_key -> correlation_id
_session_keys: OrderedDict[str, str] = OrderedDict()  # session_id -> session_key
_session_store = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _remember(mapping: OrderedDict, key: str, value: str) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > _MAX_TRACKED:
        mapping.popitem(last=False)


def _emit(stage: str, platform: str, correlation_id: str | None = None, **extra) -> None:
    event = {"stage": stage, "platform": platform, "correlation_id": correlation_id, "occurred_at": _now()}
    event.update({k: v for k, v in extra.items() if v is not None})
    with _lock:
        if len(_buffer) >= _MAX_BUFFER:
            _buffer.pop(0)
        _buffer.append(event)


def _emit_message(**message) -> None:
    with _lock:
        if len(_messages) >= _MAX_BUFFER:
            _messages.pop(0)
        _messages.append(message)


def _conversation_type(chat_type: object) -> str:
    return "DM" if str(chat_type).lower() in {"dm", "direct", "direct_message"} else "CHANNEL"


def platform_stage(state: str | None) -> str | None:
    return _PLATFORM_STAGES.get(state or "")


def obligation_stage(state: str | None) -> str | None:
    return _OBLIGATION_STAGES.get(state or "")


def _on_pre_gateway_dispatch(event=None, gateway=None, session_store=None, **_):
    global _session_store
    if session_store is not None:
        _session_store = session_store
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", "")
    message_id = getattr(event, "message_id", None) or getattr(source, "message_id", None)
    if not platform or not message_id:
        return
    correlation_id = f"{platform}:{message_id}"
    _emit("provider_observed", platform, correlation_id)
    try:
        session_key = gateway._session_key_for_source(source)  # ty: ignore[unresolved-attribute]
    except Exception:
        session_key = None
    if session_key:
        with _lock:
            _remember(_latest_inbound, session_key, correlation_id)
        text = getattr(event, "text", None)
        if text:
            _emit_message(
                platform=platform,
                provider_message_id=str(message_id),
                session_key=session_key,
                channel_id=str(getattr(source, "chat_id", "")),
                thread_id=getattr(source, "thread_id", None) or getattr(source, "parent_chat_id", None),
                direction="INBOUND",
                conversation_type=_conversation_type(getattr(source, "chat_type", None)),
                sender_id=getattr(source, "user_id", None),
                sender_name=getattr(source, "user_name", None) or getattr(source, "username", None),
                channel_name=getattr(source, "chat_name", None),
                content=str(text),
                occurred_at=_now(),
            )


def _session_key_for(session_id: str | None) -> str | None:
    if not session_id:
        return None
    with _lock:
        cached = _session_keys.get(session_id)
    if cached or _session_store is None:
        return cached
    try:
        for entry in _session_store.list_sessions():
            if getattr(entry, "session_id", None) == session_id:
                with _lock:
                    _remember(_session_keys, session_id, entry.session_key)
                return entry.session_key
    except Exception as exc:
        logger.warning("agentbarn-observer could not read the session store: %s", exc)
    return None


def _correlated(session_key: str | None) -> str | None:
    if not session_key:
        return None
    with _lock:
        return _latest_inbound.get(session_key)


def _on_run_hook(stage: str):
    def hook(session_id=None, platform="", **_):
        correlation_id = _correlated(_session_key_for(session_id))
        # Cron, BOOT.md, and API-server runs have no inbound message to report against.
        if correlation_id:
            _emit(stage, platform or correlation_id.split(":", 1)[0], correlation_id)

    return hook


def _on_approval(stage: str):
    def hook(session_key=None, surface=None, choice=None, **_):
        correlation_id = _correlated(session_key)
        if correlation_id:
            _emit(stage, correlation_id.split(":", 1)[0], correlation_id, surface=surface, choice=choice)

    return hook


def poll_platform_health(status_path: Path, last: dict[str, str]) -> None:
    try:
        platforms = json.loads(status_path.read_text()).get("platforms") or {}
    except (OSError, ValueError):
        return
    for platform, payload in platforms.items():
        if ":" in platform or not isinstance(payload, dict):
            continue  # secondary-profile entries; Agent Barn runs one profile
        state = payload.get("state")
        stage = platform_stage(state)
        if stage and last.get(platform) != state:
            last[platform] = state
            _emit(stage, platform, error_code=(payload.get("error_code") or "")[:100] or None)


def poll_obligations(db_path: Path, watermark: list[float]) -> None:
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1) as conn:
            rows = conn.execute(
                "SELECT obligation_id, session_key, platform, chat_id, thread_id, content, state, updated_at"
                " FROM delivery_obligations"
                " WHERE updated_at > ? ORDER BY updated_at",
                (watermark[0],),
            ).fetchall()
    except sqlite3.Error:
        return  # table absent until the first final response
    for obligation_id, session_key, platform, chat_id, thread_id, content, state, updated_at in rows:
        watermark[0] = max(watermark[0], updated_at)
        stage = obligation_stage(state)
        if stage:
            error_code = "send_failed" if state == "failed" else None
            _emit(stage, platform, _correlated(session_key), error_code=error_code)
            if state == "attempting" and content:
                _emit_message(
                    platform=platform,
                    provider_message_id=f"outbound:{obligation_id}",
                    session_key=session_key,
                    channel_id=chat_id,
                    thread_id=thread_id,
                    direction="OUTBOUND",
                    conversation_type="DM" if ":dm:" in session_key else "CHANNEL",
                    content=content,
                    occurred_at=_now(),
                )


def _flush(url: str, api_key: str) -> None:
    with _lock:
        events = _buffer[:]
        messages = _messages[:]
        _buffer.clear()
        _messages.clear()
    if not events and not messages:
        return
    request = urllib.request.Request(
        url,
        data=json.dumps({"events": events, "messages": messages}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except Exception as exc:
        # ponytail: best-effort journal, drops on a failed flush; add retry if gaps show up in diagnostics.
        logger.warning("agentbarn-observer dropped %d events and %d messages: %s", len(events), len(messages), exc)


def _loop(url: str, api_key: str, home: Path) -> None:
    health: dict[str, str] = {}
    # Start at boot so a restart does not replay the whole ledger.
    watermark = [time.time()]
    while True:
        time.sleep(_POLL_SECONDS)
        try:
            poll_platform_health(home / "gateway_state.json", health)
            poll_obligations(home / "state.db", watermark)
            _flush(url, api_key)
        except Exception as exc:
            logger.warning("agentbarn-observer poll failed: %s", exc)


def register(ctx):
    agent_id = os.environ.get("AGENT_ID", "")
    ingest_url = os.environ.get("INGEST_URL", "")
    api_key = os.environ.get("INGEST_API_KEY", "")
    if not agent_id or not ingest_url or not api_key:
        return

    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", _on_run_hook("agent_claimed"))
    ctx.register_hook("post_llm_call", _on_run_hook("model_completed"))
    ctx.register_hook("pre_approval_request", _on_approval("approval_requested"))
    ctx.register_hook("post_approval_response", _on_approval("approval_answered"))

    home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    url = f"{ingest_url}/agents/{agent_id}/communication-events"
    threading.Thread(target=_loop, args=(url, api_key, home), daemon=True).start()
