import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ADAPTER_PATH = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "communications-runtime-adapter.py"


def _load_adapter(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key, value in {
        "COMMUNICATIONS_URL": "http://communications.test",
        "COMMUNICATIONS_API_KEY": "communications-key",
        "AGENT_ID": "agent-1",
        "RUNTIME_API_URL": "http://runtime.test",
        "RUNTIME_API_KEY": "runtime-key",
        "RUNTIME_MODEL": "test-model",
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("communications_runtime_adapter_test", _ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load Communications runtime adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
