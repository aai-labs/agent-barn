"""Push messages and tool calls to the ingest API."""

import json
import logging
import os
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

_buffer = []
_buffer_lock = threading.Lock()
_tool_call_ids = {}
_tool_call_ids_lock = threading.Lock()
_counter = 0
_counter_lock = threading.Lock()

_last_channel = {}
_last_channel_lock = threading.Lock()

_agent_id = None
_ingest_url = None
_ingest_api_key = None
_flush_thread = None


def _next_counter():
    global _counter
    with _counter_lock:
        _counter += 1
        return _counter


def _build_session_key(chat_type, chat_id):
    prefix = "dm" if chat_type == "dm" else "group"
    return f"agent:main:slack:{prefix}:{chat_id}"


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _flush():
    with _buffer_lock:
        if not _buffer:
            return
        events = list(_buffer)
        _buffer.clear()

    messages = []
    tool_calls = []
    tool_results = []

    for event in events:
        if event["type"] == "message":
            messages.append(event["data"])
        elif event["type"] == "tool_call":
            tool_calls.append(event["data"])
        elif event["type"] == "tool_result":
            tool_results.append(event["data"])

    body = json.dumps({
        "messages": messages,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
    }).encode("utf-8")

    url = f"{_ingest_url}/agents/{_agent_id}/events"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_ingest_api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            pass
    except Exception as e:
        logger.warning("telemetry-push flush failed: %s", e)


def _flush_loop():
    while True:
        time.sleep(2)
        try:
            _flush()
        except Exception as e:
            logger.warning("telemetry-push flush loop error: %s", e)


def _on_pre_gateway_dispatch(event, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    chat_id = str(getattr(source, "chat_id", "") or "")
    user_id = str(getattr(source, "user_id", "") or "")
    thread_id = str(getattr(source, "thread_id", "") or "") or None
    text = str(getattr(event, "text", "") or "")
    _thread_ctx_end = "[End of thread context]"
    idx = text.find(_thread_ctx_end)
    if idx != -1:
        text = text[idx + len(_thread_ctx_end):].strip()
    ts = _now_iso()
    msg_id = f"hermes:in:{chat_id}:{int(time.time() * 1000)}:{_next_counter()}"
    session_key = _build_session_key(chat_type, chat_id)
    if thread_id:
        session_key = f"{session_key}:{thread_id}"
    conv_type = "DM" if chat_type == "dm" else "CHANNEL"

    with _last_channel_lock:
        _last_channel["channel_id"] = chat_id
        _last_channel["chat_type"] = chat_type
        _last_channel["thread_id"] = thread_id

    with _buffer_lock:
        _buffer.append({
            "type": "message",
            "data": {
                "msg_id": msg_id,
                "session_key": session_key,
                "channel_id": chat_id,
                "thread_id": thread_id,
                "direction": "INBOUND",
                "conversation_type": conv_type,
                "sender_id": user_id,
                "sender_name": None,
                "channel_name": None,
                "content": text,
                "occurred_at": ts,
            },
        })
    return None


def _on_post_llm_call(session_id=None, user_message=None, assistant_response=None, **kwargs):
    if not assistant_response:
        return
    ts = _now_iso()

    with _last_channel_lock:
        channel_id = _last_channel.get("channel_id", "")
        chat_type = _last_channel.get("chat_type", "dm")
        thread_id = _last_channel.get("thread_id")

    conv_type = "DM" if chat_type == "dm" else "CHANNEL"
    session_key = _build_session_key(chat_type, channel_id)
    if thread_id:
        session_key = f"{session_key}:{thread_id}"
    msg_id = f"hermes:out:{channel_id}:{int(time.time() * 1000)}:{_next_counter()}"

    with _buffer_lock:
        _buffer.append({
            "type": "message",
            "data": {
                "msg_id": msg_id,
                "session_key": session_key,
                "channel_id": channel_id,
                "thread_id": thread_id,
                "direction": "OUTBOUND",
                "conversation_type": conv_type,
                "sender_id": None,
                "sender_name": None,
                "channel_name": None,
                "content": assistant_response,
                "occurred_at": ts,
            },
        })


def _on_pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
    ts = _now_iso()
    external_id = f"hermes:{task_id}:{tool_name}:{int(time.time() * 1000)}:{_next_counter()}"

    with _tool_call_ids_lock:
        key = f"{task_id}:{tool_name}"
        _tool_call_ids[key] = external_id

    with _buffer_lock:
        _buffer.append({
            "type": "tool_call",
            "data": {
                "external_id": external_id,
                "session_id": task_id or "",
                "tool_name": tool_name or "",
                "arguments": args or {},
                "occurred_at": ts,
            },
        })
    return None


def _on_post_tool_call(tool_name=None, args=None, result=None, task_id=None, duration_ms=None, **kwargs):
    ts = _now_iso()
    key = f"{task_id}:{tool_name}"
    with _tool_call_ids_lock:
        external_id = _tool_call_ids.pop(key, None)

    if external_id is None:
        external_id = f"hermes:{task_id}:{tool_name}:{int(time.time() * 1000)}:{_next_counter()}"

    with _buffer_lock:
        _buffer.append({
            "type": "tool_result",
            "data": {
                "external_id": external_id,
                "result": result,
                "is_error": False,
                "completed_at": ts,
            },
        })


def _on_session_end(**kwargs):
    try:
        _flush()
    except Exception as e:
        logger.warning("telemetry-push session_end flush failed: %s", e)


def register(ctx):
    global _agent_id, _ingest_url, _ingest_api_key, _flush_thread

    _agent_id = os.environ.get("AGENT_ID", "")
    _ingest_url = os.environ.get("INGEST_URL", "")
    _ingest_api_key = os.environ.get("INGEST_API_KEY", "")

    if not _agent_id or not _ingest_url or not _ingest_api_key:
        return

    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)

    _flush_thread = threading.Thread(target=_flush_loop, daemon=True)
    _flush_thread.start()
