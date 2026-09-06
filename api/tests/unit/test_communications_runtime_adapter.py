import importlib.util
import json
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ADAPTER_PATH = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "communications-runtime-adapter.py"


def _load_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime_kind: str | None = None,
    verbose_mode: bool | None = None,
) -> ModuleType:
    env = {
        "COMMUNICATIONS_URL": "http://communications.test",
        "COMMUNICATIONS_API_KEY": "communications-key",
        "AGENT_ID": "agent-1",
        "RUNTIME_API_URL": "http://runtime.test",
        "RUNTIME_API_KEY": "runtime-key",
        "RUNTIME_MODEL": "test-model",
    }
    if runtime_kind is not None:
        env["RUNTIME_KIND"] = runtime_kind
    if verbose_mode is not None:
        env["VERBOSE_MODE"] = "true" if verbose_mode else "false"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("communications_runtime_adapter_test", _ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load Communications runtime adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sse_bytes(events: list[tuple[str, dict]]) -> list[bytes]:
    """Mirrors Hermes's real wire format: no `event:` SSE field, just a bare
    `data:` line whose JSON body carries the type in its own "event" key."""
    lines: list[bytes] = []
    for event, payload in events:
        lines.append(f"data: {json.dumps({**payload, 'event': event})}\n".encode())
        lines.append(b"\n")
    return lines


class _StreamStillOpen(BaseException):
    """Marks the point a fake SSE response would otherwise block forever on a
    real, still-connected stream (e.g. Hermes holding a run open pending
    approval). Deliberately not an Exception subclass so it passes through
    the adapter's `except Exception` handlers uncaught, unlike a real EOF."""


class _FakeSSEResponse:
    def __init__(self, lines: list[bytes], *, then_block: bool = False) -> None:
        self._lines = lines
        self._then_block = then_block

    def __enter__(self):
        def _iter():
            yield from self._lines
            if self._then_block:
                raise _StreamStillOpen

        return _iter()

    def __exit__(self, *_args: object) -> bool:
        return False


_DELIVERY: dict[str, Any] = {
    "delivery_id": "delivery-1",
    "connection_id": "conn-1",
    "envelope": {"text": "hello", "location": {"id": "chan-1", "thread_id": None}},
}


def _fake_urlopen(events: list[tuple[str, dict]], *, then_block: bool = False):
    def _urlopen(_req, timeout=900):
        return _FakeSSEResponse(_sse_bytes(events), then_block=then_block)

    return _urlopen


def test_idle_claim_backoff_is_bounded_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    backoff = adapter.IdleClaimBackoff(
        initial_seconds=0.5,
        max_seconds=3.0,
        multiplier=2.0,
        jitter_ratio=0,
        random_value=lambda: 0.5,
    )

    assert [backoff.next_delay() for _ in range(5)] == [0.5, 1.0, 2.0, 3.0, 3.0]
    backoff.reset()
    assert backoff.next_delay() == 0.5


def test_idle_backoff_does_not_delay_the_next_claim_after_prompt_work(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    backoff = adapter.IdleClaimBackoff(jitter_ratio=0, random_value=lambda: 0.5)
    monkeypatch.setattr(adapter, "IdleClaimBackoff", lambda: backoff)
    delivery = {"delivery_id": "delivery-1"}
    responses: list[dict | None | BaseException] = [None, None, delivery, KeyboardInterrupt()]
    events: list[tuple[str, object]] = []

    def fake_claim(*_args, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        events.append(("claim", response))
        return response

    monkeypatch.setattr(adapter, "http_request", fake_claim)
    monkeypatch.setattr(adapter, "run_delivery", lambda item: events.append(("run", item)))
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    with pytest.raises(KeyboardInterrupt):
        adapter.main()

    assert events == [
        ("claim", None),
        ("sleep", 0.5),
        ("claim", None),
        ("sleep", 1.0),
        ("claim", delivery),
        ("run", delivery),
    ]


def test_hermes_run_completed_relays_only_the_final_reply_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=False)
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen(
            [
                ("tool.started", {"tool": "web_search", "preview": "rback meaning"}),
                ("run.completed", {"text": "final answer"}),
            ]
        ),
    )

    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    reply_texts = [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_texts == ["final answer"]
    complete_calls = [payload for url, payload in calls if url.endswith("/complete")]
    assert complete_calls == [{"succeeded": True}]


def test_hermes_verbose_mode_relays_progress_events_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=True)
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen(
            [
                ("tool.started", {"tool": "search_files", "preview": "rbac"}),
                ("run.completed", {"text": "final answer"}),
            ]
        ),
    )

    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    reply_texts = [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_texts == ['Searching the codebase for files matching "rbac"', "final answer"]


def test_progress_line_renders_full_sentences_for_known_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=True)

    assert (
        adapter._progress_line("tool.started", {"tool": "search_files", "preview": "rbac"})
        == 'Searching the codebase for files matching "rbac"'
    )
    assert (
        adapter._progress_line("tool.started", {"tool": "read_file", "preview": "catalog.py L1-120"})
        == "Reading catalog.py (lines 1-120)"
    )
    assert (
        adapter._progress_line("tool.started", {"tool": "write_file", "preview": "/opt/data/notes.md"})
        == "Writing changes to /opt/data/notes.md"
    )
    assert (
        adapter._progress_line("tool.started", {"tool": "memory", "preview": '+memory: "Remembered word: pineapple"'})
        == "Saving a note to memory: Remembered word: pineapple"
    )
    assert (
        adapter._progress_line("subagent.start", {"goal": "audit RBAC"}) == "Starting a subagent to work on: audit RBAC"
    )
    assert adapter._progress_line("tool.started", {"tool": "web_search", "preview": "hermes docs"}) == (
        "Running web_search: hermes docs"
    )


def test_hermes_reasoning_available_is_never_relayed_even_with_verbose_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed against a live run: reasoning.available is a preview of the
    final answer truncated at a fixed length, not a distinct "thinking" step —
    relaying it produces a cut-off message followed by the full one. It must
    never be posted, regardless of verbose mode."""
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=True)
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen(
            [
                ("reasoning.available", {"text": "Here are 4 things rback could mean:\n\n1. RBAC — a common sec"}),
                (
                    "run.completed",
                    {"output": "Here are 4 things rback could mean:\n\n1. RBAC — a common security model..."},
                ),
            ]
        ),
    )

    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    reply_texts = [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_texts == ["Here are 4 things rback could mean:\n\n1. RBAC — a common security model..."]


def test_hermes_reclaim_does_not_start_a_second_concurrent_run_for_the_same_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow turn that outlives the 120s claim lease gets reclaimed and
    re-claimed server-side while the original background thread is still
    genuinely working — starting a second /v1/runs here would double the work
    and race two runs against the same session's memory."""
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    run_calls: list[dict] = []
    release = threading.Event()

    def fake_http_request(method, url, *, headers, payload=None):
        if url.endswith("/v1/runs"):
            assert payload is not None
            run_calls.append(payload)
            release.wait(timeout=5)
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", _fake_urlopen([("run.completed", {"output": "done"})]))

    session_key = adapter.session_key_for(_DELIVERY)
    adapter.run_delivery_hermes(_DELIVERY)
    try:
        assert adapter._ACTIVE_RUNS[session_key].is_alive()
        reclaimed_delivery = {**_DELIVERY, "delivery_id": "delivery-2"}
        adapter.run_delivery_hermes(reclaimed_delivery)
    finally:
        release.set()
        adapter._ACTIVE_RUNS[session_key].join(timeout=5)

    assert len(run_calls) == 1
    assert session_key not in adapter._ACTIVE_RUNS


def test_hermes_approval_request_relays_regardless_of_verbose_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=False)
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen(
            [
                ("approval.request", {"command": "rm -rf /tmp/x", "choices": ["once", "deny"]}),
            ],
            then_block=True,
        ),
    )

    session_key = adapter.session_key_for(_DELIVERY)
    with pytest.raises(_StreamStillOpen):
        adapter._run_and_drain(_DELIVERY, session_key)

    reply_calls = [payload for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert len(reply_calls) == 1
    assert "rm -rf /tmp/x" in reply_calls[0]["text"]
    assert not any(url.endswith("/complete") for url, _ in calls)
    assert adapter._PENDING_APPROVALS[session_key]["run_id"] == "run-1"


def test_hermes_second_delivery_for_pending_session_resolves_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-1",
        "delivery_id": "delivery-1",
        "choices": ["once", "deny"],
    }
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter,
        "_run_and_drain",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not start a new run")),
    )

    reply_delivery = {**_DELIVERY, "delivery_id": "delivery-2", "envelope": {**_DELIVERY["envelope"], "text": "once"}}
    adapter.run_delivery_hermes(reply_delivery)

    approval_calls = [(url, payload) for url, payload in calls if url.endswith("/v1/runs/run-1/approval")]
    assert approval_calls == [("http://runtime.test/v1/runs/run-1/approval", {"choice": "once"})]
    assert session_key not in adapter._PENDING_APPROVALS
    complete_calls = [(url, payload) for url, payload in calls if url.endswith("/complete")]
    assert complete_calls == [
        (
            "http://communications.test/agents/agent-1/deliveries/delivery-2/complete",
            {"succeeded": True},
        )
    ]


def test_hermes_stream_closing_without_a_terminal_event_fails_the_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run whose SSE stream ends without run.completed/failed (e.g. Hermes
    crashed mid-run) must not be left dangling for the lease-expiry reclaim to
    silently retry forever with no visible error."""
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen([("reasoning.available", {"text": "thinking..."})]),
    )

    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    complete_calls = [payload for url, payload in calls if url.endswith("/complete")]
    assert complete_calls == [
        {"succeeded": False, "error_code": "RuntimeError", "error_message": "Run run-1 events stream ended early"}
    ]


def test_hermes_delivery_explicitly_resumes_its_durable_session(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    requests = []
    monkeypatch.setattr(
        adapter,
        "http_request",
        lambda method, url, **kwargs: requests.append(kwargs) or {"run_id": "run-1"},
    )
    monkeypatch.setattr(adapter, "_drain_run", lambda *args: None)

    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    assert requests[0]["payload"] == {
        "input": "hello",
        "session_id": "connection:conn-1:chan-1:root",
        "resume_session": True,
    }
