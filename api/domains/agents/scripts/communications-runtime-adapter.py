"""Bridge the Agent Barn Communications protocol to a local runtime HTTP API."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "messaging"))
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from agentbarn_message import bind_execution, unbind_execution  # ty: ignore[unresolved-import]

COMMUNICATIONS_URL = os.environ["COMMUNICATIONS_URL"].rstrip("/")
COMMUNICATIONS_API_KEY = os.environ["COMMUNICATIONS_API_KEY"]
COMMUNICATIONS_PROTOCOL_VERSION = os.environ.get("COMMUNICATIONS_PROTOCOL_VERSION", "2")
AGENT_ID = os.environ["AGENT_ID"]
RUNTIME_API_URL = os.environ["RUNTIME_API_URL"].rstrip("/")
RUNTIME_API_KEY = os.environ["RUNTIME_API_KEY"]
RUNTIME_MODEL = os.environ["RUNTIME_MODEL"]
# "hermes" drives the async /v1/runs API below; anything else (including unset,
# for OpenClaw pods which don't set this) keeps the original blocking
# /v1/chat/completions call, since only Hermes exposes the run/event/approval API.
RUNTIME_KIND = os.environ.get("RUNTIME_KIND", "openclaw")
VERBOSE_MODE = os.environ.get("VERBOSE_MODE", "false").lower() == "true"
CLAIM_SAFETY_POLL_INTERVAL_SECONDS = 5
PENDING_CANCEL_TTL_SECONDS = 900
MAX_PENDING_CANCEL_REQUESTS = 1_024

# Runs currently waiting on a human approval, keyed by session. Process-local:
# lost on a pod restart, same as an in-flight blocking call is today.
_PENDING_APPROVALS_LOCK = threading.Lock()
_PENDING_APPROVALS: dict[str, dict] = {}

# The thread currently draining a run for a session, if any. Prevents a
# reclaimed delivery (lease expired while a run is still genuinely in
# progress) from starting a second concurrent run against the same session.
_ACTIVE_RUNS_LOCK = threading.Lock()
_ACTIVE_RUNS: dict[str, ActiveRun] = {}

# Communications control-plane calls (claim, reply, complete, renew) and the
# runtime's own run/approval endpoints all answer immediately, so a peer that
# stops responding must surface as an error the surrounding retry loop can act
# on. It cannot be left to block: the delivery worker claims inside this call,
# so a long stall there stops claiming entirely and logs nothing at all --
# indistinguishable from an idle queue.
_REQUEST_TIMEOUT_SECONDS = 30
# The one exception: OpenClaw's blocking turn holds the connection open for the
# whole model response.
_RUNTIME_TURN_TIMEOUT_SECONDS = 900

_LEASE_HEARTBEAT_SECONDS = 60
_PROGRESS_RELAY_MIN_SECONDS = 3


class ActiveRun:
    def __init__(self, delivery_id: str, thread: threading.Thread) -> None:
        self.delivery_id = delivery_id
        self.thread = thread

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout)


class InFlightDelivery:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._delivery_id: str | None = None
        self._session_key: str | None = None
        self._cancel_requested = False
        self._pending_cancel_requests: dict[str, float] = {}

    def begin(self, delivery_id: str, session_key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune_pending_cancels(now)
            self._delivery_id = delivery_id
            self._session_key = session_key
            self._cancel_requested = self._pending_cancel_requests.pop(delivery_id, None) is not None

    def clear(self, delivery_id: str) -> None:
        with self._lock:
            if self._delivery_id != delivery_id:
                return
            self._delivery_id = None
            self._session_key = None
            self._cancel_requested = False
            self._pending_cancel_requests.pop(delivery_id, None)

    def request_cancel(self, delivery_id: str) -> str | None:
        with self._lock:
            if self._delivery_id != delivery_id:
                now = time.monotonic()
                self._prune_pending_cancels(now)
                self._pending_cancel_requests[delivery_id] = now
                if len(self._pending_cancel_requests) > MAX_PENDING_CANCEL_REQUESTS:
                    oldest_delivery_id = min(self._pending_cancel_requests.items(), key=lambda item: item[1])[0]
                    del self._pending_cancel_requests[oldest_delivery_id]
                return None
            self._cancel_requested = True
            return self._session_key

    def is_cancel_requested(self, delivery_id: str) -> bool:
        with self._lock:
            return self._delivery_id == delivery_id and self._cancel_requested

    def _prune_pending_cancels(self, now: float) -> None:
        cutoff = now - PENDING_CANCEL_TTL_SECONDS
        for delivery_id, requested_at in list(self._pending_cancel_requests.items()):
            if requested_at < cutoff:
                del self._pending_cancel_requests[delivery_id]


IN_FLIGHT = InFlightDelivery()


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict | None = None,
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 204:
                return None
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def communications_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {COMMUNICATIONS_API_KEY}",
        "X-AgentBarn-Communications-Version": COMMUNICATIONS_PROTOCOL_VERSION,
        "Content-Type": "application/json",
    }


def runtime_headers(session_key: str, idempotency_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {RUNTIME_API_KEY}",
        "Content-Type": "application/json",
        "X-OpenClaw-Session-Key": session_key,
        "X-Hermes-Session-Key": session_key,
        "Idempotency-Key": idempotency_key,
    }


def session_key_for(delivery: dict) -> str:
    envelope = delivery["envelope"]
    return (
        f"connection:{delivery['connection_id']}:"
        f"{envelope['location']['id']}:{envelope['location'].get('thread_id') or 'root'}"
    )


def request_local_cancel(delivery_id: str) -> None:
    # Neither pinned runtime exposes a proven abort handle for the OpenAI-style
    # chat-completions request. Marking the in-flight turn is still immediate:
    # its eventual result is suppressed locally and rejected atomically by the
    # durable source-delivery check in Communications.
    IN_FLIGHT.request_cancel(delivery_id)


def post_reply(delivery_id: str, text: str, *, suffix: str = "") -> None:
    idempotency_key = f"{delivery_id}:{suffix}" if suffix else delivery_id
    http_request(
        "POST",
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/replies",
        headers=communications_headers(),
        payload={"idempotency_key": idempotency_key, "text": text},
    )


def complete_delivery(delivery_id: str, *, succeeded: bool, error: Exception | None = None) -> None:
    completion: dict = {"succeeded": succeeded}
    if error is not None:
        completion["error_code"] = type(error).__name__
        completion["error_message"] = str(error)[:500]
    http_request(
        "POST",
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/complete",
        headers=communications_headers(),
        payload=completion,
    )


def renew_delivery_lease(delivery_id: str, *, awaiting_input: bool = False) -> None:
    http_request(
        "POST",
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/renew"
        f"?awaiting_input={'true' if awaiting_input else 'false'}",
        headers=communications_headers(),
    )


def _is_awaiting_input(session_key: str) -> bool:
    with _PENDING_APPROVALS_LOCK:
        return session_key in _PENDING_APPROVALS


def _publish_awaiting_input(delivery_id: str, session_key: str) -> None:
    """Push the session's current parked state without waiting for the next
    heartbeat, which would otherwise hold an answer for up to a full interval.

    The value is read here rather than passed in: a run that parks again right
    after an approval resolves must not be un-parked by the resolving call.
    """
    try:
        renew_delivery_lease(delivery_id, awaiting_input=_is_awaiting_input(session_key))
    except Exception as exc:
        # The heartbeat re-sends this state every interval, so a lost
        # transition costs latency, not correctness.
        print(f"[communications-adapter] awaiting-input publish failed: {exc}", flush=True)


def _heartbeat_delivery_lease(delivery_id: str, stopped: threading.Event, session_key: str) -> None:
    while not stopped.wait(_LEASE_HEARTBEAT_SECONDS):
        try:
            renew_delivery_lease(delivery_id, awaiting_input=_is_awaiting_input(session_key))
        except Exception as exc:
            # A transient renewal failure must not interrupt a healthy Hermes
            # run; the next heartbeat can still extend its original lease.
            print(f"[communications-adapter] lease renewal failed: {exc}", flush=True)


def post_reply_best_effort(delivery_id: str, text: str, *, suffix: str = "") -> None:
    try:
        post_reply(delivery_id, text, suffix=suffix)
    except Exception as exc:
        # Progress and approval notices improve visibility, but neither is the
        # turn result. Keep draining so the final response can still arrive.
        print(f"[communications-adapter] progress relay failed: {exc}", flush=True)


def run_delivery_chat_completions(delivery: dict) -> None:
    """Original single blocking-turn path, kept for OpenClaw pods."""
    delivery_id = delivery["delivery_id"]
    envelope = delivery["envelope"]
    session_key = session_key_for(delivery)
    IN_FLIGHT.begin(delivery_id, session_key)
    bind_execution(session_key, delivery)
    try:
        result = http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/chat/completions",
            headers=runtime_headers(session_key, delivery_id),
            timeout=_RUNTIME_TURN_TIMEOUT_SECONDS,
            payload={
                "model": RUNTIME_MODEL,
                "stream": False,
                "user": session_key,
                "messages": [{"role": "user", "content": envelope.get("text", "")}],
            },
        )
        if IN_FLIGHT.is_cancel_requested(delivery_id):
            completion: dict = {
                "succeeded": False,
                "error_code": "CANCELLED",
                "error_message": "Cancelled by user",
            }
        else:
            reply = result["choices"][0]["message"]["content"]
            post_reply(delivery_id, reply)
            completion = {"succeeded": True}
    except Exception as exc:
        completion = {
            "succeeded": False,
            "error_code": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
    try:
        http_request(
            "POST",
            f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/complete",
            headers=communications_headers(),
            payload=completion,
        )
    finally:
        IN_FLIGHT.clear(delivery_id)
        unbind_execution(session_key)


def iter_sse_events(response):
    """Minimal SSE reader: yields (event, data) per blank-line-terminated block."""
    event = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if data_lines:
        yield event, "\n".join(data_lines)


# Providers wrap mentions and links in their own angle-bracket markup, and a
# reply that answers an approval carries it like any other message
# ("<@U0BTHDYS4TY> always"). A model reading a turn can ignore that; an exact
# choice match cannot, so it is stripped here rather than in any one plugin --
# Slack, Discord, and Teams all reach this same comparison.
_PROVIDER_MARKUP = re.compile(r"<[^>]*>")


def resolve_pending_approval(session_key: str, delivery: dict) -> bool:
    """If session_key has a run waiting on approval, submit this delivery's text
    as the answer. Returns True once this delivery has been fully handled."""
    with _PENDING_APPROVALS_LOCK:
        pending = _PENDING_APPROVALS.get(session_key)
    if pending is None:
        return False

    delivery_id = delivery["delivery_id"]
    choice = _PROVIDER_MARKUP.sub(" ", delivery["envelope"].get("text", "")).strip().lower()
    try:
        http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/runs/{pending['run_id']}/approval",
            headers=runtime_headers(session_key, delivery_id),
            payload={"choice": choice},
        )
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("HTTP 400"):
            # Invalid choice: re-prompt, leave the pending entry in place, and
            # treat this delivery as handled (we did get a reply, just not a
            # usable one).
            choices = ", ".join(pending["choices"])
            post_reply(delivery_id, f"Please reply with one of: {choices}")
            complete_delivery(delivery_id, succeeded=True)
            return True
        if message.startswith(("HTTP 404", "HTTP 409")):
            # The run resolved some other way (e.g. Hermes's own approval
            # timeout). Drop the stale entry and let the caller start a fresh run.
            with _PENDING_APPROVALS_LOCK:
                _PENDING_APPROVALS.pop(session_key, None)
            return False
        complete_delivery(delivery_id, succeeded=False, error=exc)
        return True

    with _PENDING_APPROVALS_LOCK:
        _PENDING_APPROVALS.pop(session_key, None)
    _publish_awaiting_input(pending["delivery_id"], session_key)
    complete_delivery(delivery_id, succeeded=True)
    return True


def run_delivery_hermes(delivery: dict) -> None:
    session_key = session_key_for(delivery)
    if resolve_pending_approval(session_key, delivery):
        return
    active_delivery_id: str | None = None
    with _ACTIVE_RUNS_LOCK:
        existing = _ACTIVE_RUNS.get(session_key)
        if existing is not None and existing.is_alive():
            if existing.delivery_id == delivery["delivery_id"]:
                # This is the same lease-reclaimed delivery. Its live owner
                # will produce the reply and completion once the run ends.
                return
            active_delivery_id = existing.delivery_id
        else:
            thread = threading.Thread(target=_run_and_drain, args=(delivery, session_key), daemon=True)
            _ACTIVE_RUNS[session_key] = ActiveRun(delivery_id=delivery["delivery_id"], thread=thread)
    if active_delivery_id is not None:
        # A later message is a distinct durable delivery, not a reclaim.
        # Acknowledge it immediately instead of letting it churn through lease
        # expiry while preserving session ordering.
        post_reply(delivery["delivery_id"], "I'm still working on your previous message. Please try again shortly.")
        complete_delivery(delivery["delivery_id"], succeeded=True)
        return
    thread.start()


def _run_and_drain(delivery: dict, session_key: str) -> None:
    delivery_id = delivery["delivery_id"]
    text = delivery["envelope"].get("text", "")
    heartbeat_stopped = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_delivery_lease,
        args=(delivery_id, heartbeat_stopped, session_key),
        daemon=True,
    )
    heartbeat.start()
    bind_execution(session_key, delivery)
    try:
        started = http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/runs",
            headers=runtime_headers(session_key, delivery_id),
            payload={"input": text, "session_id": session_key, "resume_session": True},
        )
        _drain_run(
            started["run_id"],
            delivery_id,
            session_key,
            progress_updates=delivery.get("progress_updates", True),
        )
    except Exception as exc:
        with _PENDING_APPROVALS_LOCK:
            _PENDING_APPROVALS.pop(session_key, None)
        complete_delivery(delivery_id, succeeded=False, error=exc)
    finally:
        unbind_execution(session_key)
        heartbeat_stopped.set()
        with _ACTIVE_RUNS_LOCK:
            active = _ACTIVE_RUNS.get(session_key)
            if active is not None and active.thread is threading.current_thread():
                del _ACTIVE_RUNS[session_key]


# Hermes's tool.started "preview" is a bare argument (a search query, a
# "file.py L1-120" range, a path) with no sentence around it — relayed as-is
# it reads as disconnected noise ("rbac", "catalog.py L1-120"). Each of these
# turns the argument into a full, self-explanatory sentence instead of just
# a verb stuck in front of the raw value.
_READ_FILE_RANGE = re.compile(r"^(?P<path>.+) L(?P<start>\d+)-(?P<end>\d+)$")


def _progress_line(event: str, payload: dict) -> str:
    if event in ("subagent.start", "subagent.complete"):
        goal = payload.get("goal") or "a subtask"
        return f"Starting a subagent to work on: {goal}" if event == "subagent.start" else f"Subagent finished: {goal}"

    tool = payload.get("tool")
    preview = (payload.get("preview") or "").strip()

    if tool == "search_files":
        return f'Searching the codebase for files matching "{preview}"' if preview else "Searching the codebase"
    if tool == "read_file":
        match = _READ_FILE_RANGE.match(preview)
        if match:
            return f"Reading {match['path']} (lines {match['start']}-{match['end']})"
        return f"Reading {preview}" if preview else "Reading a file"
    if tool == "write_file":
        return f"Writing changes to {preview}" if preview else "Writing a file"
    if tool == "memory":
        note = preview.removeprefix("+memory:").strip().strip('"')
        return f"Saving a note to memory: {note}" if note else "Saving a note to memory"

    if tool and preview:
        return f"Running {tool}: {preview}"
    return preview or tool or event


def _drain_run(run_id: str, delivery_id: str, session_key: str, *, progress_updates: bool = True) -> None:
    req = urllib.request.Request(
        f"{RUNTIME_API_URL}/v1/runs/{run_id}/events",
        method="GET",
        headers={
            "Authorization": f"Bearer {RUNTIME_API_KEY}",
            "Accept": "text/event-stream",
            "X-Hermes-Session-Key": session_key,
        },
    )
    sequence = 0
    last_progress_at = float("-inf")
    with urllib.request.urlopen(req, timeout=900) as response:
        for sse_event, data in iter_sse_events(response):
            if not data:
                continue
            sequence += 1
            payload = json.loads(data)
            # Hermes never sends an `event:` SSE field — every frame is a bare
            # `data:` line whose JSON body carries the type in "event".
            event = payload.get("event", sse_event)

            if event == "approval.request":
                choices = payload.get("choices") or ["once", "session", "always", "deny"]
                with _PENDING_APPROVALS_LOCK:
                    _PENDING_APPROVALS[session_key] = {
                        "run_id": run_id,
                        "delivery_id": delivery_id,
                        "choices": choices,
                    }
                # Release this delivery's hold on the thread: the answer can
                # only arrive as the next message here, and it cannot be
                # claimed while this run counts as blocking.
                _publish_awaiting_input(delivery_id, session_key)
                description = payload.get("command") or payload.get("description") or "A command needs approval"
                post_reply_best_effort(
                    delivery_id,
                    f"{description}\nReply with one of: {', '.join(choices)}",
                    suffix=str(sequence),
                )
                continue

            # reasoning.available is deliberately not relayed here: it's a
            # preview of the eventual answer truncated at a fixed length (not
            # a distinct "thinking" step), so it always either duplicates or
            # cuts off the real final reply below.
            if event in ("tool.started", "subagent.start", "subagent.complete"):
                if (
                    VERBOSE_MODE
                    and progress_updates
                    and time.monotonic() - last_progress_at >= _PROGRESS_RELAY_MIN_SECONDS
                ):
                    post_reply_best_effort(delivery_id, _progress_line(event, payload), suffix=str(sequence))
                    last_progress_at = time.monotonic()
                continue

            if event == "run.completed":
                post_reply(delivery_id, payload.get("text") or payload.get("output") or "", suffix=str(sequence))
                with _PENDING_APPROVALS_LOCK:
                    _PENDING_APPROVALS.pop(session_key, None)
                complete_delivery(delivery_id, succeeded=True)
                return

            if event in ("run.failed", "run.cancelled"):
                with _PENDING_APPROVALS_LOCK:
                    _PENDING_APPROVALS.pop(session_key, None)
                complete_delivery(
                    delivery_id, succeeded=False, error=RuntimeError(payload.get("error") or f"Run {event}")
                )
                return

    # The stream closed without a terminal event: fail the delivery instead of
    # silently returning, so it dead-letters on retry exhaustion rather than
    # spinning on the lease-expiry reclaim forever.
    with _PENDING_APPROVALS_LOCK:
        _PENDING_APPROVALS.pop(session_key, None)
    complete_delivery(delivery_id, succeeded=False, error=RuntimeError(f"Run {run_id} events stream ended early"))


def run_delivery(delivery: dict) -> None:
    if RUNTIME_KIND == "hermes":
        run_delivery_hermes(delivery)
    else:
        run_delivery_chat_completions(delivery)


class DeliveryWorker:
    """Drain durable claims on signals, with a bounded lost-wakeup fallback."""

    def __init__(self) -> None:
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="communications-delivery", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while True:
            # Redis is only a wakeup optimization. A publish can fail after
            # PostgreSQL commits, so periodically retry the durable claim even
            # when the control stream has not delivered a signal.
            self._wake.wait(timeout=CLAIM_SAFETY_POLL_INTERVAL_SECONDS)
            self._wake.clear()
            try:
                self._drain()
            except Exception as exc:
                print(f"[communications-adapter] delivery worker: {exc}", flush=True)
                time.sleep(2)
                self._wake.set()

    def _drain(self) -> None:
        while True:
            delivery = http_request(
                "POST",
                f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/claim",
                headers=communications_headers(),
            )
            if delivery is None:
                return
            run_delivery(delivery)


def consume_control_stream(worker: DeliveryWorker) -> None:
    req = urllib.request.Request(
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/control",
        method="GET",
        headers={
            "Authorization": f"Bearer {COMMUNICATIONS_API_KEY}",
            "X-AgentBarn-Communications-Version": COMMUNICATIONS_PROTOCOL_VERSION,
            "Accept": "text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        for raw_line in response:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if event.get("type") == "delivery_available":
                worker.wake()
            elif event.get("type") == "delivery_cancelled" and event.get("delivery_id"):
                request_local_cancel(event["delivery_id"])


def main() -> None:
    worker = DeliveryWorker()
    worker.start()
    reconnect_delay = 1
    while True:
        try:
            consume_control_stream(worker)
            print("[communications-adapter] control stream closed; reconnecting", flush=True)
        except Exception as exc:
            print(f"[communications-adapter] control stream: {exc}", flush=True)
        time.sleep(reconnect_delay)
        reconnect_delay = min(15, reconnect_delay * 2)


if __name__ == "__main__":
    main()
