"""A turn stopped by a model spend limit must tell the person chatting why (AF-337).

The runtime cannot be relied on to carry the reason out: OpenClaw rewrites the
proxy's message into its own billing error and Hermes aborts the turn. So the
in-pod proxy records the refusal, the adapter in the same container reports it as
SPEND_LIMIT_REACHED when the turn fails, and Communications turns that code into
the notice shown under the message (web chat) or posted in the channel.
"""

import json
import os
import time

import pytest
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, is_, starts_with

from api.domains.communications.error_details import normalize_communication_error
from api.tests.unit.test_agent_llm_error_proxy import BUDGET_BODY, UNKNOWN_MODEL_BODY, _post, _proxy, _upstream
from api.tests.unit.test_communications_runtime_adapter import _DELIVERY, _fake_urlopen, _load_adapter

SPEND_LIMIT_NOTICE = (
    "This agent has reached its model spend limit. "
    "Contact your administrator to raise it or wait for the limit to renew."
)


@pytest.fixture
def marker(tmp_path, monkeypatch):
    path = tmp_path / "llm-terminal-error.json"
    monkeypatch.setenv("AGENTBARN_LLM_ERROR_MARKER", str(path))
    return path


def write_marker(path, *, at: float) -> None:
    path.write_text(json.dumps({"code": "SPEND_LIMIT_REACHED", "at": at}))


# --- the in-pod proxy records why it refused --------------------------------------


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_spend_limit_refusal_is_recorded_for_the_adapter(runtime, marker):
    with _upstream(429, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        before = time.time()
        _post(proxy)
    recorded = json.loads(marker.read_text())
    assert_that(recorded["code"], equal_to("SPEND_LIMIT_REACHED"))
    assert_that(recorded["at"] >= before - 1, is_(True))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_other_provider_errors_leave_no_record(runtime, marker):
    with _upstream(400, UNKNOWN_MODEL_BODY) as target, _proxy(runtime, target) as proxy:
        _post(proxy)
    assert_that(marker.exists(), is_(False))


# --- the adapter reports it when the turn fails -----------------------------------


def completions(calls):
    return [payload for url, payload in calls if url.endswith("/complete")]


def test_an_openclaw_turn_stopped_by_the_limit_is_reported_as_such(monkeypatch, marker):
    adapter = _load_adapter(monkeypatch, runtime_kind="openclaw")
    calls = []

    def fake_http_request(method, url, *, headers, payload=None, timeout=None):
        calls.append((url, payload))
        if url.endswith("/v1/chat/completions"):
            # The proxy refused a model call during this turn; OpenClaw then
            # answered with its own, unrelated error.
            write_marker(marker, at=time.time())
            raise RuntimeError("HTTP 402: returned a billing error")

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    adapter.run_delivery_chat_completions(_DELIVERY)

    assert_that(completions(calls), contains_exactly(has_entries(succeeded=False, error_code="SPEND_LIMIT_REACHED")))


def test_a_refusal_from_an_earlier_turn_is_not_blamed_for_this_one(monkeypatch, marker):
    adapter = _load_adapter(monkeypatch, runtime_kind="openclaw")
    write_marker(marker, at=time.time() - 3600)
    calls = []

    def fake_http_request(method, url, *, headers, payload=None, timeout=None):
        calls.append((url, payload))
        if url.endswith("/v1/chat/completions"):
            raise RuntimeError("HTTP 500: internal error")

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    adapter.run_delivery_chat_completions(_DELIVERY)

    assert_that(completions(calls), contains_exactly(has_entries(succeeded=False, error_code="RuntimeError")))


def test_a_hermes_run_stopped_by_the_limit_is_reported_as_such(monkeypatch, marker):
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls = []

    def fake_http_request(method, url, *, headers, payload=None, timeout=None):
        calls.append((url, payload))
        if url.endswith("/v1/runs"):
            write_marker(marker, at=time.time())
            return {"run_id": "run-1"}
        return None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        _fake_urlopen([("run.failed", {"error": "Error code: 402 - billing"})]),
    )
    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    assert_that(completions(calls), contains_exactly(has_entries(succeeded=False, error_code="SPEND_LIMIT_REACHED")))


def test_no_record_at_all_keeps_the_runtimes_own_error(monkeypatch, marker):
    adapter = _load_adapter(monkeypatch, runtime_kind="hermes")
    calls = []

    def fake_http_request(method, url, *, headers, payload=None, timeout=None):
        calls.append((url, payload))
        return {"run_id": "run-1"} if url.endswith("/v1/runs") else None

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", _fake_urlopen([("run.failed", {"error": "boom"})]))
    adapter._run_and_drain(_DELIVERY, adapter.session_key_for(_DELIVERY))

    assert_that(
        completions(calls),
        equal_to([{"succeeded": False, "error_code": "RuntimeError", "error_message": "boom"}]),
    )


# --- Communications turns the code into the notice --------------------------------


def test_the_code_becomes_the_spend_limit_notice_and_is_not_retried():
    normalized = normalize_communication_error(
        error_code="SPEND_LIMIT_REACHED",
        error_message="HTTP 402: returned a billing error — your API key has run out of credits",
        operation="runtime_processing",
    )
    assert_that(normalized.code, equal_to("SPEND_LIMIT_REACHED"))
    # Said plainly, without "(HTTP 402, ...)": this is read by the person chatting.
    assert_that(normalized.summary, equal_to(SPEND_LIMIT_NOTICE))
    assert normalized.details is not None
    assert_that(normalized.details.retryable, is_(False))


def test_a_genuine_provider_billing_error_keeps_its_own_notice():
    normalized = normalize_communication_error(
        error_code="RuntimeError", error_message="HTTP 402: insufficient credits", operation="runtime_processing"
    )
    assert_that(normalized.summary or "", starts_with("The provider reports exhausted credits"))


def test_the_marker_path_is_shared_by_proxy_and_adapter():
    """Both sides must agree on the default, or the record is written where nobody reads."""
    from pathlib import Path

    scripts = Path(__file__).parents[2] / "domains" / "agents" / "scripts"
    default = "/tmp/agentbarn-llm-terminal-error.json"
    for script in ("hermes/healthz-server.py", "openclaw/healthz-server.js", "communications-runtime-adapter.py"):
        assert_that(default in (scripts / script).read_text(), is_(True), script)
    assert_that(os.path.basename(default), equal_to("agentbarn-llm-terminal-error.json"))


@pytest.mark.parametrize(
    "content",
    ['{"code": "SPEND_LIMIT_REACHED", "at": "soon"}', '{"code": "SPEND_LIMIT_REACHED", "at": [1]}', "[1, 2]", "{"],
)
def test_a_malformed_record_is_ignored_rather_than_breaking_the_turn(monkeypatch, marker, content):
    """The runtime shares the container and could leave anything in the file; the
    delivery must still complete with the runtime's own error."""
    adapter = _load_adapter(monkeypatch, runtime_kind="openclaw")
    calls = []

    def fake_http_request(method, url, *, headers, payload=None, timeout=None):
        calls.append((url, payload))
        if url.endswith("/v1/chat/completions"):
            marker.write_text(content)
            raise RuntimeError("HTTP 500: internal error")

    monkeypatch.setattr(adapter, "http_request", fake_http_request)
    adapter.run_delivery_chat_completions(_DELIVERY)

    assert_that(completions(calls), contains_exactly(has_entries(succeeded=False, error_code="RuntimeError")))
