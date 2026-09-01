import importlib.util
import io
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

_ADAPTER_PATH = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "communications-runtime-adapter.py"


def _load_adapter(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key, value in {
        "COMMUNICATIONS_URL": "http://communications.test",
        "COMMUNICATIONS_API_KEY": "communications-key",
        "COMMUNICATIONS_PROTOCOL_VERSION": "2",
        "AGENT_ID": "agent-1",
        "RUNTIME_API_URL": "http://runtime.test",
        "RUNTIME_API_KEY": "runtime-key",
        "RUNTIME_MODEL": "test-model",
        "AGENT_RUNTIME_KIND": "hermes",
    }.items():
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


def test_run_delivery_posts_reply_then_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    calls: list[tuple[str, dict | None]] = []

    def fake_request(_method: str, url: str, *, headers: dict[str, str], payload: dict | None = None):
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


def test_cancel_during_runtime_work_suppresses_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter(monkeypatch)
    calls: list[tuple[str, dict | None]] = []

    def fake_request(_method: str, url: str, *, headers: dict[str, str], payload: dict | None = None):
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
