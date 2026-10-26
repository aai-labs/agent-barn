import ast
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


def test_listener_source_parses_for_the_oldest_runtime_image() -> None:
    ast.parse(_SCRIPT.read_text(), filename=str(_SCRIPT), feature_version=(3, 12))


@pytest.mark.parametrize(
    "reply",
    [
        '{"summary":"CRM unavailable", "criteria_met":false}\nNote: config uses {braces}.',
        'Config uses {braces}.\n```json\n{"summary":"CRM unavailable", "criteria_met":false}\n```',
        '{"summary":"CRM {unavailable}", "criteria_met":false} trailing {text}',
    ],
)
def test_explicit_failure_survives_surrounding_braces(trigger_server, reply) -> None:
    met, summary = trigger_server._parse_step_reply(reply)
    assert met is False
    assert summary.startswith("CRM")


def test_hermes_stop_uses_the_original_session_header(monkeypatch, trigger_server) -> None:
    requests = []

    class Response:
        def close(self):
            pass

    monkeypatch.setattr(
        trigger_server.urllib.request, "urlopen", lambda request, **kw: requests.append(request) or Response()
    )
    trigger_server.RUNTIME_KIND = "hermes"
    trigger_server.RUNTIME_API_URL = "http://runtime"
    trigger_server._STEPS["a"] = {"run_id": "run-1", "session_id": "workflow-a", "stopped": False}
    trigger_server.stop_workflow_step("a")
    assert requests[0].full_url.endswith("/v1/runs/run-1/stop")
    assert requests[0].get_header("X-hermes-session-key") == "workflow-a"


def test_cancellation_while_hermes_start_is_in_flight_stops_the_accepted_run(monkeypatch, trigger_server) -> None:
    trigger_server.RUNTIME_API_URL = "http://runtime"
    trigger_server.RUNTIME_KIND = "hermes"
    trigger_server._STEPS["a"] = {"run_id": None, "stopped": False}
    stopped = []

    class Response:
        def __enter__(self):
            trigger_server.stop_workflow_step("a")
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"run_id":"run-1"}'

    monkeypatch.setattr(trigger_server.urllib.request, "urlopen", lambda *args, **kw: Response())
    monkeypatch.setattr(trigger_server, "_stop_hermes", lambda *args: stopped.append(args))
    with pytest.raises(RuntimeError, match="cancelled"):
        trigger_server._hermes_step("a", "workflow-a", "Do the step")
    assert stopped == [("run-1", "workflow-a")]


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


def test_a_create_the_runtime_refused_outright_can_be_retried_with_the_same_key(
    monkeypatch, tmp_path, trigger_server
) -> None:
    trigger_server.RECEIPT_PATH = tmp_path / "receipts.sqlite3"
    trigger_server.RUNTIME_KIND = "hermes"
    key = f"{_payload()['invocation_id']}:1"

    def refused(name, prompt, platform):
        raise trigger_server.NotSubmittedError("connection refused")

    monkeypatch.setattr(trigger_server, "_hermes_find", lambda name: None)
    monkeypatch.setattr(trigger_server, "_hermes_create", refused)
    with pytest.raises(trigger_server.DispatchError):
        trigger_server.dispatch(key, _payload())

    monkeypatch.setattr(trigger_server, "_hermes_create", lambda *args: "hermes-job-1")
    assert trigger_server.dispatch(key, _payload()) == "hermes-job-1"


def test_a_refused_runtime_connection_proves_nothing_was_submitted(monkeypatch, trigger_server) -> None:
    import urllib.error

    def refuse(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError())

    trigger_server.RUNTIME_API_URL = "http://runtime"
    monkeypatch.setattr(trigger_server.urllib.request, "urlopen", refuse)

    with pytest.raises(trigger_server.NotSubmittedError):
        trigger_server._request_json("POST", "/api/jobs", {})


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


# Workflow steps --------------------------------------------------------------


def _step_reports(monkeypatch, trigger_server, reply=None, error=None, runtime="hermes"):
    trigger_server.RUNTIME_KIND = runtime
    reports = []

    def post(url, token, body, *, method="POST"):
        if url.endswith("/handoff"):
            return {"session_id": "workflow-a", "prompt": "Do the step"}
        reports.append((url.rsplit("/", 1)[1], body))
        return None

    def run(*args):
        if error:
            raise error
        return reply

    monkeypatch.setattr(trigger_server, "_post_json", post)
    monkeypatch.setattr(trigger_server, "_hermes_step", run)
    monkeypatch.setattr(trigger_server, "_openclaw_step", run)
    trigger_server._STEPS["a"] = {"run_id": None, "stopped": False}
    trigger_server._run_workflow_step("a", "token", "http://api/attempts/a")
    return reports


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_completed_step_reports_the_agents_summary(monkeypatch, trigger_server, runtime) -> None:
    reply = 'Done.\n```json\n{"summary": "Found 3 leads", "criteria_met": true}\n```'
    reports = _step_reports(monkeypatch, trigger_server, reply=reply, runtime=runtime)
    assert reports == [("result", {"summary": "Found 3 leads", "criteria_met": True})]
    assert "a" not in trigger_server._STEPS


def test_plain_prose_still_counts_as_the_step_summary(monkeypatch, trigger_server) -> None:
    reports = _step_reports(monkeypatch, trigger_server, reply="Found 3 leads in HubSpot.")
    assert reports == [("result", {"summary": "Found 3 leads in HubSpot.", "criteria_met": True})]


def test_unmet_criteria_are_reported_as_a_failure(monkeypatch, trigger_server) -> None:
    reply = '{"summary": "HubSpot is not connected", "criteria_met": false}'
    reports = _step_reports(monkeypatch, trigger_server, reply=reply)
    assert reports == [("failure", {"reason": "HubSpot is not connected"})]


def test_an_approval_request_is_reported_as_needing_attention(monkeypatch, trigger_server) -> None:
    error = trigger_server.NeedsAttention("The Agent needs approval to run ls.")
    reports = _step_reports(monkeypatch, trigger_server, error=error)
    assert reports == [("failure", {"reason": "The Agent needs approval to run ls.", "needs_attention": True})]


def test_a_stopped_step_reports_nothing(monkeypatch, trigger_server) -> None:
    trigger_server.RUNTIME_KIND = "hermes"
    reports = []
    monkeypatch.setattr(
        trigger_server,
        "_post_json",
        lambda url, token, body, method="POST": (
            {"session_id": "s", "prompt": "p"} if url.endswith("/handoff") else reports.append(body)
        ),
    )

    def stopped(*args):
        trigger_server._STEPS["a"]["stopped"] = True
        raise RuntimeError("Agent session cancelled")

    monkeypatch.setattr(trigger_server, "_hermes_step", stopped)
    trigger_server._STEPS["a"] = {"run_id": None, "stopped": False}
    trigger_server._run_workflow_step("a", "token", "http://api/attempts/a")
    assert reports == []


def test_a_step_is_started_once_per_attempt(monkeypatch, trigger_server) -> None:
    started = []
    monkeypatch.setattr(trigger_server, "_run_workflow_step", lambda *args: started.append(args))
    payload = {
        "attempt_id": "018f0f6d-2d51-7d82-a8ef-1b646c15bd8e",
        "token": "token",
        "callback_url": "http://api/attempts/x",
    }
    assert trigger_server.start_workflow_step(payload) is True
    assert trigger_server.start_workflow_step(payload) is False
    with pytest.raises(ValueError):
        trigger_server.start_workflow_step(
            {**payload, "attempt_id": "018f0f6d-2d51-7d82-a8ef-1b646c15bd8f", "token": ""}
        )


def test_hermes_step_runs_a_new_session_and_reads_the_final_reply(trigger_server) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = {}

    class FakeHermes(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["start"] = (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            seen["session_header"] = self.headers["X-Hermes-Session-Key"]
            body = json.dumps({"run_id": "run-1"}).encode()
            self.send_response(202)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen["events"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in ({"event": "tool.started"}, {"event": "run.completed", "text": "All done"}):
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHermes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        trigger_server.RUNTIME_API_URL = f"http://127.0.0.1:{server.server_port}"
        trigger_server._STEPS["a"] = {"run_id": None, "stopped": False}
        assert trigger_server._hermes_step("a", "workflow-a", "Do the step") == "All done"
    finally:
        server.shutdown()
    assert seen["start"] == ("/v1/runs", {"input": "Do the step", "session_id": "workflow-a"})
    assert seen["session_header"] == "workflow-a"
    assert seen["events"] == "/v1/runs/run-1/events"
    assert trigger_server._STEPS["a"]["run_id"] == "run-1"
