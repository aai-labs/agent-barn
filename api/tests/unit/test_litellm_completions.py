"""The completion client against a loopback stand-in for the LiteLLM proxy."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to, has_entries

from api.infrastructure.litellm.completions import (
    CompletionError,
    CompletionFailure,
    CompletionResult,
    LiteLLMCompletionClient,
)


@dataclass
class StubProxy:
    status: int = 200
    body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def litellm_proxy(stub: StubProxy) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            stub.requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "json": json.loads(self.rfile.read(length)),
                }
            )
            payload = json.dumps(stub.body).encode()
            self.send_response(stub.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in stub.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _client(base_url: str) -> LiteLLMCompletionClient:
    config = MagicMock()
    config.litellm_base_url = base_url
    return LiteLLMCompletionClient(config=config)


def _complete(stub: StubProxy, **options: Any) -> CompletionResult:
    with litellm_proxy(stub) as base_url:
        return _client(base_url).complete(
            "sk-agent-key",
            "openrouter/openai/gpt-4.1-mini",
            [{"role": "user", "content": "Summarise"}],
            max_tokens=500,
            **options,
        )


def _answer(content: Any = "A playbook", usage: dict | None = None) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": usage or {}}


def test_the_request_carries_the_agent_key_model_and_json_mode():
    stub = StubProxy(body=_answer())

    _complete(stub, json_response=True)

    [request] = stub.requests
    assert_that(request["path"], equal_to("/chat/completions"))
    assert_that(request["authorization"], equal_to("Bearer sk-agent-key"))
    assert_that(
        request["json"],
        has_entries(
            model="openrouter/openai/gpt-4.1-mini",
            max_tokens=500,
            messages=[{"role": "user", "content": "Summarise"}],
            response_format={"type": "json_object"},
        ),
    )


def test_text_usage_and_reported_cost_are_returned():
    stub = StubProxy(
        body=_answer("## Playbook", {"prompt_tokens": 1200, "completion_tokens": 300}),
        headers={"x-litellm-response-cost": "0.00042"},
    )

    result = _complete(stub)

    assert_that(result, equal_to(CompletionResult("## Playbook", 1200, 300, Decimal("0.00042"))))


def test_a_missing_or_malformed_cost_is_unknown_rather_than_zero():
    result = _complete(StubProxy(body=_answer(), headers={"x-litellm-response-cost": "NaN"}))

    assert_that(result.cost_usd, equal_to(None))


@pytest.mark.parametrize(
    "status,body,failure",
    [
        (400, {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded"}}, "budget_exceeded"),
        (429, {"error": {"type": "rate_limit", "message": "ExceededBudget: team budget"}}, "budget_exceeded"),
        (401, {"error": {"type": "auth_error", "message": "Invalid key"}}, "key_or_model_rejected"),
        (400, {"error": {"type": "invalid_request", "message": "Unknown model"}}, "key_or_model_rejected"),
        (429, {"error": {"type": "rate_limit", "message": "Slow down"}}, "unavailable"),
        (502, {"error": "upstream"}, "unavailable"),
    ],
)
def test_proxy_errors_are_classified_without_their_text(status, body, failure):
    with pytest.raises(CompletionError) as raised:
        _complete(StubProxy(status=status, body=body))

    assert_that(raised.value.failure, equal_to(CompletionFailure(failure)))
    assert_that(str(raised.value), equal_to(failure))


@pytest.mark.parametrize("body", [_answer(""), _answer(None), {"choices": []}, ["not", "an", "object"]])
def test_an_answer_without_text_is_a_bad_response(body):
    with pytest.raises(CompletionError) as raised:
        _complete(StubProxy(body=body))

    assert_that(raised.value.failure, equal_to(CompletionFailure.BAD_RESPONSE))


def test_an_unreachable_proxy_is_unavailable():
    with litellm_proxy(StubProxy()) as base_url:
        pass

    with pytest.raises(CompletionError) as raised:
        _client(base_url).complete("sk-agent-key", "m", [], max_tokens=10, timeout_seconds=2)

    assert_that(raised.value.failure, equal_to(CompletionFailure.UNAVAILABLE))
