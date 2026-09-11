import ast
import importlib.util
import io
import json
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Self
from unittest.mock import Mock, call

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
        "COMMUNICATIONS_PROTOCOL_VERSION": "2",
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


def _delivery() -> dict:
    return {
        "delivery_id": "delivery-1",
        "connection_id": "connection-1",
        "envelope": {
            "text": "hello",
            "location": {"id": "user-1", "thread_id": "thread-1"},
        },
    }


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


def test_adapter_source_parses_for_the_oldest_runtime_image() -> None:
    ast.parse(_ADAPTER_PATH.read_text(), filename=str(_ADAPTER_PATH), feature_version=(3, 12))


def test_run_delivery_posts_reply_then_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    calls: list[tuple[str, dict | None]] = []

    def fake_request(_method: str, url: str, *, headers: dict[str, str], payload: dict | None = None, **_):
        del headers
        calls.append((url, payload))
        if url.endswith("/v1/chat/completions"):
            return {"choices": [{"message": {"content": "agent reply"}}]}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_request)

    adapter.run_delivery(_delivery())

    assert [url for url, _ in calls] == [
        "http://runtime.test/v1/chat/completions",
        "http://communications.test/agents/agent-1/deliveries/delivery-1/replies",
        "http://communications.test/agents/agent-1/deliveries/delivery-1/complete",
    ]
    assert calls[1][1] == {"idempotency_key": "delivery-1", "text": "agent reply"}
    assert calls[2][1] == {"succeeded": True}


def test_communications_calls_are_bounded_so_a_stall_cannot_park_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delivery worker claims inside http_request, so an unbounded wait there
    stops claiming entirely and logs nothing -- indistinguishable from idle."""
    adapter = _load_adapter(monkeypatch)
    timeouts: list[float | None] = []

    class Response:
        status = 204

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> bool:
            return False

    def fake_urlopen(_req: Any, timeout: float | None = None) -> Response:
        timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)

    adapter.renew_delivery_lease("delivery-1")

    assert timeouts == [adapter._REQUEST_TIMEOUT_SECONDS]
    assert adapter._REQUEST_TIMEOUT_SECONDS < adapter._RUNTIME_TURN_TIMEOUT_SECONDS


def test_cancel_during_runtime_work_suppresses_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    calls: list[tuple[str, dict | None]] = []

    def fake_request(_method: str, url: str, *, headers: dict[str, str], payload: dict | None = None, **_):
        del headers
        calls.append((url, payload))
        if url.endswith("/v1/chat/completions"):
            adapter.request_local_cancel("delivery-1")
            return {"choices": [{"message": {"content": "late reply"}}]}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_request)

    adapter.run_delivery(_delivery())

    assert not any(url.endswith("/replies") for url, _ in calls)
    assert calls[-1][1] == {
        "succeeded": False,
        "error_code": "CANCELLED",
        "error_message": "Cancelled by user",
    }


def test_cancel_before_delivery_start_is_applied_when_delivery_begins(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    in_flight = adapter.InFlightDelivery()

    assert in_flight.request_cancel("delivery-1") is None
    in_flight.begin("delivery-1", "session-1")

    assert in_flight.is_cancel_requested("delivery-1") is True


def test_control_stream_wakes_delivery_worker_and_routes_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    worker = Mock()
    cancel = Mock()
    monkeypatch.setattr(adapter, "request_local_cancel", cancel)
    response = io.BytesIO(
        b'data: {"type":"delivery_available"}\n\n'
        b'data: {"type":"delivery_cancelled","delivery_id":"delivery-1"}\n\n'
        b"data: not-json\n\n"
    )

    class Response:
        status = 200

        def __enter__(self):
            return response

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(adapter.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    adapter.consume_control_stream(worker)

    worker.wake.assert_called_once_with()
    cancel.assert_called_once_with("delivery-1")


def test_main_backs_off_after_a_clean_control_stream_close(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    worker = Mock()
    monkeypatch.setattr(adapter, "DeliveryWorker", lambda: worker)
    monkeypatch.setattr(adapter, "consume_control_stream", Mock(side_effect=[None, KeyboardInterrupt]))
    sleep = Mock()
    monkeypatch.setattr(adapter.time, "sleep", sleep)

    with pytest.raises(KeyboardInterrupt):
        adapter.main()

    worker.start.assert_called_once_with()
    sleep.assert_has_calls([call(1)])


def test_delivery_worker_safety_poll_claims_without_a_control_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    delivery = _delivery()
    responses: list[dict | None] = [delivery, None]
    claim = Mock(side_effect=lambda *_args, **_kwargs: responses.pop(0))
    run_delivery = Mock()
    monkeypatch.setattr(adapter, "http_request", claim)
    monkeypatch.setattr(adapter, "run_delivery", run_delivery)

    class Wake:
        def __init__(self) -> None:
            self.wait_calls: list[float] = []
            self.wait_count = 0

        def wait(self, *, timeout: float) -> bool:
            self.wait_calls.append(timeout)
            self.wait_count += 1
            if self.wait_count == 1:
                return False
            raise KeyboardInterrupt

        def clear(self) -> None:
            return None

    wake = Wake()
    worker = adapter.DeliveryWorker()
    worker._wake = wake

    with pytest.raises(KeyboardInterrupt):
        worker._run()

    assert wake.wait_calls == [adapter.CLAIM_SAFETY_POLL_INTERVAL_SECONDS] * 2
    assert claim.call_count == 2
    run_delivery.assert_called_once_with(delivery)


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


def test_progress_events_are_withheld_from_a_platform_that_refuses_them(monkeypatch: pytest.MonkeyPatch) -> None:
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
                ("subagent.start", {"goal": "check the mailbox"}),
                ("run.completed", {"text": "final answer"}),
            ]
        ),
    )
    delivery = {**_DELIVERY, "progress_updates": False}

    adapter._run_and_drain(delivery, adapter.session_key_for(delivery))

    reply_texts = [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_texts == ["final answer"]


def test_approval_requests_reach_a_platform_that_refuses_progress_events(monkeypatch: pytest.MonkeyPatch) -> None:
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
                ("approval.request", {"command": "rm -rf build", "choices": ["once", "deny"]}),
            ],
            then_block=True,
        ),
    )
    delivery = {**_DELIVERY, "progress_updates": False}

    with pytest.raises(_StreamStillOpen):
        adapter._run_and_drain(delivery, adapter.session_key_for(delivery))

    reply_texts = [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_texts == ["```\nrm -rf build\n```\nReply with one of: once, deny"]


def test_approval_prompt_keeps_a_long_command_reviewable(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    limit = adapter._APPROVAL_COMMAND_MAX_CHARS

    short = adapter._approval_prompt("echo hi", ["once", "deny"])
    assert short == "```\necho hi\n```\nReply with one of: once, deny"

    overlong = adapter._approval_prompt("x" * (limit + 40), ["once"])
    assert "[40 more characters not shown]" in overlong
    assert overlong.startswith("```\n") and overlong.endswith("Reply with one of: once")

    escaped = adapter._approval_prompt("cat <<'EOF'\n```\nEOF", ["once"])
    assert escaped.count("```") == 2


def test_a_late_approval_answer_is_not_handed_to_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        adapter, "http_request", lambda method, url, *, headers, payload=None: calls.append((url, payload))
    )

    delivery = {**_DELIVERY, "envelope": {**_DELIVERY["envelope"], "text": "once"}}
    handled = adapter.resolve_pending_approval(adapter.session_key_for(delivery), delivery)

    assert handled is True
    assert not any(url.endswith("/approval") for url, _ in calls)
    assert [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None] == [
        "No command is waiting for approval."
    ]


def test_an_ordinary_message_is_untouched_when_no_approval_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")

    handled = adapter.resolve_pending_approval(adapter.session_key_for(_DELIVERY), _DELIVERY)

    assert handled is False


def test_a_click_from_an_already_resolved_run_cannot_answer_the_current_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        adapter, "http_request", lambda method, url, *, headers, payload=None: calls.append((url, payload))
    )

    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-2",
        "delivery_id": "delivery-1",
        "choices": ["once", "deny"],
    }
    delivery = {
        **_DELIVERY,
        "envelope": {**_DELIVERY["envelope"], "text": "once", "provider_metadata": {"approval_run_id": "run-1"}},
    }

    handled = adapter.resolve_pending_approval(session_key, delivery)

    assert handled is True
    assert not any(url.endswith("/approval") for url, _ in calls)
    assert adapter._PENDING_APPROVALS[session_key]["run_id"] == "run-2"


def test_a_click_from_the_pending_run_resolves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        adapter, "http_request", lambda method, url, *, headers, payload=None: calls.append((url, payload))
    )

    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-1",
        "delivery_id": "delivery-1",
        "choices": ["once", "deny"],
    }
    delivery = {
        **_DELIVERY,
        "envelope": {**_DELIVERY["envelope"], "text": "once", "provider_metadata": {"approval_run_id": "run-1"}},
    }

    assert adapter.resolve_pending_approval(session_key, delivery) is True
    assert [payload for url, payload in calls if url.endswith("/approval")] == [{"choice": "once"}]
    assert session_key not in adapter._PENDING_APPROVALS


def _drain_one_approval(adapter, monkeypatch: pytest.MonkeyPatch, choices: list[str]) -> tuple[dict, str]:
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
        _fake_urlopen([("approval.request", {"command": "rm -rf build", "choices": choices})], then_block=True),
    )
    session_key = adapter.session_key_for(_DELIVERY)
    with pytest.raises(_StreamStillOpen):
        adapter._run_and_drain(_DELIVERY, session_key)
    return next(payload for url, payload in calls if url.endswith("/replies") and payload), session_key


def test_manual_mode_offers_only_per_command_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_MODE", "manual")
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")

    reply, session_key = _drain_one_approval(adapter, monkeypatch, ["once", "session", "always", "deny"])

    assert reply["approval"]["choices"] == ["once", "deny"]
    assert reply["text"].endswith("Reply with one of: once, deny")
    assert adapter._PENDING_APPROVALS[session_key]["choices"] == ["once", "deny"]


def test_auto_mode_still_offers_every_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPROVAL_MODE", raising=False)
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")

    reply, _ = _drain_one_approval(adapter, monkeypatch, ["once", "session", "always", "deny"])

    assert reply["approval"]["choices"] == ["once", "session", "always", "deny"]


def test_an_answer_that_was_not_offered_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        adapter, "http_request", lambda method, url, *, headers, payload=None: calls.append((url, payload))
    )
    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-1",
        "delivery_id": "delivery-1",
        "choices": ["once", "deny"],
    }
    delivery = {**_DELIVERY, "envelope": {**_DELIVERY["envelope"], "text": "always"}}

    assert adapter.resolve_pending_approval(session_key, delivery) is True
    assert not any(url.endswith("/approval") for url, _ in calls)
    assert [payload["text"] for url, payload in calls if url.endswith("/replies") and payload is not None] == [
        "Please reply with one of: once, deny"
    ]
    assert session_key in adapter._PENDING_APPROVALS


def test_approve_still_means_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        adapter, "http_request", lambda method, url, *, headers, payload=None: calls.append((url, payload))
    )
    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-1",
        "delivery_id": "delivery-1",
        "choices": ["once", "deny"],
    }
    delivery = {**_DELIVERY, "envelope": {**_DELIVERY["envelope"], "text": "approve"}}

    assert adapter.resolve_pending_approval(session_key, delivery) is True
    assert [payload for url, payload in calls if url.endswith("/approval")] == [{"choice": "once"}]


def test_approval_prompt_idempotency_key_survives_a_redrain(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")

    first = adapter._approval_reply_suffix("run-1", "rm -rf build")
    assert first == adapter._approval_reply_suffix("run-1", "rm -rf build")
    assert first != adapter._approval_reply_suffix("run-1", "rm -rf dist")
    assert first != adapter._approval_reply_suffix("run-2", "rm -rf build")
    assert first.startswith("approval:run-1:")


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


def test_hermes_second_delivery_for_an_active_session_is_acknowledged(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls: list[tuple[str, dict | None]] = []
    release = threading.Event()

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            release.wait(timeout=5)
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", _fake_urlopen([("run.completed", {"output": "done"})]))

    session_key = adapter.session_key_for(_DELIVERY)
    adapter.run_delivery_hermes(_DELIVERY)
    try:
        second_delivery = {**_DELIVERY, "delivery_id": "delivery-2"}
        adapter.run_delivery_hermes(second_delivery)
    finally:
        release.set()
        adapter._ACTIVE_RUNS[session_key].join(timeout=5)

    reply_calls = [payload for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_calls == [
        {
            "idempotency_key": "delivery-2",
            "text": "I'm still working on your previous message. Please try again shortly.",
        },
        {"idempotency_key": "delivery-1:1", "text": "done"},
    ]
    completion_calls = [payload for url, payload in calls if url.endswith("/complete")]
    assert completion_calls == [{"succeeded": True}, {"succeeded": True}]


def test_hermes_progress_relay_is_best_effort_and_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes", verbose_mode=True)
    calls: list[tuple[str, dict | None]] = []

    def fake_http_request(method, url, *, headers, payload=None):
        calls.append((url, payload))
        if url.endswith("/replies") and payload and payload["idempotency_key"] == "delivery-1:1":
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(adapter.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen(
            [
                ("tool.started", {"tool": "search_files", "preview": "first"}),
                ("tool.started", {"tool": "search_files", "preview": "second"}),
                ("run.completed", {"text": "final answer"}),
            ]
        ),
    )

    adapter._drain_run("run-1", _DELIVERY["delivery_id"], adapter.session_key_for(_DELIVERY))

    reply_calls = [payload for url, payload in calls if url.endswith("/replies") and payload is not None]
    assert reply_calls == [
        {"idempotency_key": "delivery-1:1", "text": 'Searching the codebase for files matching "first"'},
        {"idempotency_key": "delivery-1:3", "text": "final answer"},
    ]
    assert [payload for url, payload in calls if url.endswith("/complete")] == [{"succeeded": True}]


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
    assert reply_calls[0]["approval"] == {
        "run_id": "run-1",
        "command": "rm -rf /tmp/x",
        "choices": ["once", "deny"],
    }
    assert not any(url.endswith("/complete") for url, _ in calls)
    assert adapter._PENDING_APPROVALS[session_key]["run_id"] == "run-1"


def test_an_approval_answer_is_matched_past_the_provider_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Slack reply carries the bot mention like any other message, so the raw
    envelope text is never exactly a choice and the run re-prompts forever."""
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    session_key = adapter.session_key_for(_DELIVERY)
    adapter._PENDING_APPROVALS[session_key] = {
        "run_id": "run-1",
        "delivery_id": "delivery-1",
        "choices": ["once", "session", "always", "deny"],
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

    reply_delivery = {
        **_DELIVERY,
        "delivery_id": "delivery-2",
        "envelope": {**_DELIVERY["envelope"], "text": "<@U0BTHDYS4TY> always"},
    }
    adapter.run_delivery_hermes(reply_delivery)

    approval_calls = [(url, payload) for url, payload in calls if url.endswith("/v1/runs/run-1/approval")]
    assert approval_calls == [("http://runtime.test/v1/runs/run-1/approval", {"choice": "always"})]
    assert session_key not in adapter._PENDING_APPROVALS


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
