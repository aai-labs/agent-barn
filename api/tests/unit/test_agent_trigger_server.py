import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "agent-trigger-server.py"


@pytest.fixture
def trigger_server():
    spec = importlib.util.spec_from_file_location("agent_trigger_server_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    return {
        "invocation_id": "018f0f6d-2d51-7d82-a8ef-1b646c15bd8e",
        "dispatch_generation": 1,
        "prompt": "Prepare the release notes",
        "delivery_platform": "slack",
    }


def test_dispatch_is_idempotent_after_the_native_scheduler_accepts(monkeypatch, tmp_path, trigger_server) -> None:
    trigger_server.RECEIPT_PATH = tmp_path / "receipts.sqlite3"
    trigger_server.RUNTIME_KIND = "hermes"
    calls = []

    def accept(name, prompt, platform):
        calls.append((name, prompt, platform))
        return "hermes-job-1"

    monkeypatch.setattr(trigger_server, "_hermes_find", lambda name: None)
    monkeypatch.setattr(trigger_server, "_hermes_create", accept)
    first = trigger_server.dispatch(f"{_payload()['invocation_id']}:1", _payload())
    duplicate = trigger_server.dispatch(f"{_payload()['invocation_id']}:1", _payload())

    assert first == duplicate == "hermes-job-1"
    assert len(calls) == 1


def _interrupted_create(monkeypatch, tmp_path, trigger_server) -> str:
    """The first create reaches the runtime but its response is lost."""
    trigger_server.RECEIPT_PATH = tmp_path / "receipts.sqlite3"
    trigger_server.RUNTIME_KIND = "hermes"
    key = f"{_payload()['invocation_id']}:1"

    def lost(name, prompt, platform):
        raise trigger_server.DispatchError("timed out")

    monkeypatch.setattr(trigger_server, "_hermes_find", lambda name: None)
    monkeypatch.setattr(trigger_server, "_hermes_create", lost)
    with pytest.raises(trigger_server.DispatchError):
        trigger_server.dispatch(key, _payload())
    return key


def test_a_retry_adopts_the_job_an_interrupted_create_made(monkeypatch, tmp_path, trigger_server) -> None:
    key = _interrupted_create(monkeypatch, tmp_path, trigger_server)
    monkeypatch.setattr(trigger_server, "_hermes_find", lambda name: "hermes-job-1")

    assert trigger_server.dispatch(key, _payload()) == "hermes-job-1"
    assert trigger_server.dispatch(key, _payload()) == "hermes-job-1"


def test_a_retry_never_recreates_a_job_that_may_already_have_run(monkeypatch, tmp_path, trigger_server) -> None:
    key = _interrupted_create(monkeypatch, tmp_path, trigger_server)
    created = []
    monkeypatch.setattr(trigger_server, "_hermes_create", lambda *args: created.append(args) or "second")

    with pytest.raises(trigger_server.ConflictError, match="outcome is unknown"):
        trigger_server.dispatch(key, _payload())
    assert created == []


def test_hermes_creates_a_scheduler_fired_one_shot_job_with_native_delivery(monkeypatch, trigger_server) -> None:
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, body))
        return {"job": {"id": "abcdef123456"}}

    monkeypatch.setattr(trigger_server, "_request_json", request)
    job_id = trigger_server._hermes_create("agentbarn-hook-1", "Do it", "teams")

    assert job_id == "abcdef123456"
    assert calls[0][2]["deliver"] == "teams"
    assert calls[0][2]["repeat"] == 1
    # No forced run: the scheduler fires the near-future one-shot exactly once.
    assert len(calls) == 1


def test_an_existing_native_job_is_returned_without_being_triggered_again(monkeypatch, trigger_server) -> None:
    calls = []

    def request(method, path, body=None):
        calls.append((method, path))
        return {"jobs": [{"id": "abcdef123456", "name": "agentbarn-hook-1"}]}

    monkeypatch.setattr(trigger_server, "_request_json", request)

    assert trigger_server._hermes_find("agentbarn-hook-1") == "abcdef123456"
    assert calls == [("GET", "/api/jobs?include_disabled=true")]


def test_a_runtime_client_error_is_not_retryable(monkeypatch, trigger_server) -> None:
    import urllib.error
    from email.message import Message

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("http://runtime/api/jobs", 400, "Prompt too long", Message(), None)

    trigger_server.RUNTIME_API_URL = "http://runtime"
    monkeypatch.setattr(trigger_server.urllib.request, "urlopen", reject)

    with pytest.raises(ValueError, match="HTTP 400"):
        trigger_server._request_json("POST", "/api/jobs", {})


def test_openclaw_maps_teams_to_its_native_channel_and_schedules_the_job(monkeypatch, trigger_server) -> None:
    calls = []

    def invoke(arguments):
        calls.append(arguments)
        return {"id": "openclaw-job-1"}

    monkeypatch.setattr(trigger_server, "_openclaw_json", invoke)
    job_id = trigger_server._openclaw_create("agentbarn-hook-1", "Do it", "teams")

    assert job_id == "openclaw-job-1"
    assert calls[0][calls[0].index("--channel") + 1] == "msteams"
    assert "--to" not in calls[0]
    assert len(calls) == 1
