"""Bridge the Agent Barn Communications protocol to a local runtime HTTP API."""

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

COMMUNICATIONS_URL = os.environ["COMMUNICATIONS_URL"].rstrip("/")
COMMUNICATIONS_API_KEY = os.environ["COMMUNICATIONS_API_KEY"]
AGENT_ID = os.environ["AGENT_ID"]
RUNTIME_API_URL = os.environ["RUNTIME_API_URL"].rstrip("/")
RUNTIME_API_KEY = os.environ["RUNTIME_API_KEY"]
RUNTIME_MODEL = os.environ["RUNTIME_MODEL"]
# "hermes" drives the async /v1/runs API below; anything else (including unset,
# for OpenClaw pods which don't set this) keeps the original blocking
# /v1/chat/completions call, since only Hermes exposes the run/event/approval API.
RUNTIME_KIND = os.environ.get("RUNTIME_KIND", "openclaw")
VERBOSE_MODE = os.environ.get("VERBOSE_MODE", "false").lower() == "true"

# Runs currently waiting on a human approval, keyed by session. Process-local:
# lost on a pod restart, same as an in-flight blocking call is today.
_PENDING_APPROVALS_LOCK = threading.Lock()
_PENDING_APPROVALS: dict[str, dict] = {}

# The thread currently draining a run for a session, if any. Prevents a
# reclaimed delivery (lease expired while a run is still genuinely in
# progress) from starting a second concurrent run against the same session.
_ACTIVE_RUNS_LOCK = threading.Lock()
_ACTIVE_RUNS: dict[str, threading.Thread] = {}


class IdleClaimBackoff:
    """Bound idle claim cadence while retaining prompt bounded delivery."""

    def __init__(
        self,
        *,
        initial_seconds: float = 0.5,
        max_seconds: float = 5.0,
        multiplier: float = 2.0,
        jitter_ratio: float = 0.2,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if initial_seconds <= 0 or max_seconds < initial_seconds:
            raise ValueError("Idle claim backoff bounds are invalid")
        if multiplier < 1 or not 0 <= jitter_ratio < 1:
            raise ValueError("Idle claim backoff parameters are invalid")
        self._initial_seconds = initial_seconds
        self._max_seconds = max_seconds
        self._multiplier = multiplier
        self._jitter_ratio = jitter_ratio
        self._random_value = random_value
        self._current_seconds = initial_seconds

    def next_delay(self) -> float:
        base = self._current_seconds
        self._current_seconds = min(self._max_seconds, base * self._multiplier)
        jitter = (self._random_value() * 2 - 1) * self._jitter_ratio
        return min(self._max_seconds, max(0.0, base * (1 + jitter)))

    def reset(self) -> None:
        self._current_seconds = self._initial_seconds


def http_request(method: str, url: str, *, headers: dict[str, str], payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=900) as response:
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
        "X-AgentBarn-Communications-Version": "1",
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


def run_delivery_chat_completions(delivery: dict) -> None:
    """Original single blocking-turn path, kept for OpenClaw pods."""
    delivery_id = delivery["delivery_id"]
    envelope = delivery["envelope"]
    session_key = session_key_for(delivery)
    try:
        result = http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/chat/completions",
            headers=runtime_headers(session_key, delivery_id),
            payload={
                "model": RUNTIME_MODEL,
                "stream": False,
                "user": session_key,
                "messages": [{"role": "user", "content": envelope.get("text", "")}],
            },
        )
        reply = result["choices"][0]["message"]["content"]
        post_reply(delivery_id, reply)
        completion_error = None
    except Exception as exc:
        completion_error = exc
    complete_delivery(delivery_id, succeeded=completion_error is None, error=completion_error)


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


def resolve_pending_approval(session_key: str, delivery: dict) -> bool:
    """If session_key has a run waiting on approval, submit this delivery's text
    as the answer. Returns True once this delivery has been fully handled."""
    with _PENDING_APPROVALS_LOCK:
        pending = _PENDING_APPROVALS.get(session_key)
    if pending is None:
        return False

    delivery_id = delivery["delivery_id"]
    choice = delivery["envelope"].get("text", "").strip().lower()
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
    complete_delivery(delivery_id, succeeded=True)
    return True


def run_delivery_hermes(delivery: dict) -> None:
    session_key = session_key_for(delivery)
    if resolve_pending_approval(session_key, delivery):
        return
    with _ACTIVE_RUNS_LOCK:
        existing = _ACTIVE_RUNS.get(session_key)
        if existing is not None and existing.is_alive():
            # The claim lease expired and this delivery got reclaimed while a
            # run for the same session is still genuinely in progress (e.g. a
            # slow agentic turn past the 120s lease). Starting a second run
            # here would double the work and race two runs against the same
            # session's memory. The live thread will reply/complete this same
            # delivery_id once it finishes.
            return
        thread = threading.Thread(target=_run_and_drain, args=(delivery, session_key), daemon=True)
        _ACTIVE_RUNS[session_key] = thread
    thread.start()


def _run_and_drain(delivery: dict, session_key: str) -> None:
    delivery_id = delivery["delivery_id"]
    text = delivery["envelope"].get("text", "")
    try:
        started = http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/runs",
            headers=runtime_headers(session_key, delivery_id),
            payload={"input": text, "session_id": session_key, "resume_session": True},
        )
        _drain_run(started["run_id"], delivery_id, session_key)
    except Exception as exc:
        with _PENDING_APPROVALS_LOCK:
            _PENDING_APPROVALS.pop(session_key, None)
        complete_delivery(delivery_id, succeeded=False, error=exc)
    finally:
        with _ACTIVE_RUNS_LOCK:
            if _ACTIVE_RUNS.get(session_key) is threading.current_thread():
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


def _drain_run(run_id: str, delivery_id: str, session_key: str) -> None:
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
                description = payload.get("command") or payload.get("description") or "A command needs approval"
                post_reply(
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
                if VERBOSE_MODE:
                    post_reply(delivery_id, _progress_line(event, payload), suffix=str(sequence))
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


def main() -> None:
    idle_backoff = IdleClaimBackoff()
    while True:
        try:
            delivery = http_request(
                "POST",
                f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/claim",
                headers=communications_headers(),
            )
            if delivery is None:
                time.sleep(idle_backoff.next_delay())
                continue
            idle_backoff.reset()
            run_delivery(delivery)
        except Exception as exc:
            print(f"[communications-adapter] {exc}", flush=True)
            idle_backoff.reset()
            time.sleep(2)


if __name__ == "__main__":
    main()
