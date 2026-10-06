import logging
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import httpx
import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_not

from api.core.config import Config
from api.infrastructure.posthog.client import PostHogClient
from api.infrastructure.posthog.exceptions import RetryablePostHogException, TerminalPostHogException
from api.tests.mocks.posthog import make_posthog_blocking_post

HOST = "https://eu.i.posthog.com"
TOKEN = "phc_test_token_value"
MESSAGES = [{"event": "agent.created", "distinct_id": "user-1", "properties": {}}]


def _client(host: str = HOST) -> PostHogClient:
    return PostHogClient(
        config=cast(Config, SimpleNamespace(analytics_posthog_host=host, analytics_posthog_project_token=TOKEN))
    )


def _response(status: int, text: str = "") -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("POST", f"{HOST}/batch/"))


@pytest.mark.parametrize("host", [HOST, f"{HOST}/"])
def test_sends_one_batch_request_to_the_batch_endpoint(host):
    with patch("api.infrastructure.posthog.client.httpx.post", return_value=_response(200)) as post:
        _client(host).send_batch(MESSAGES)

    assert_that(post.call_count, equal_to(1))
    assert_that(post.call_args.args[0], equal_to(f"{HOST}/batch/"))
    assert_that(post.call_args.kwargs["json"], has_entries({"api_key": TOKEN, "batch": MESSAGES}))
    assert_that(post.call_args.kwargs["json"]["sent_at"], contains_string("T"))


def test_waits_at_most_five_seconds():
    with patch("api.infrastructure.posthog.client.httpx.post", return_value=_response(200)) as post:
        _client().send_batch(MESSAGES)

    timeout: httpx.Timeout = post.call_args.kwargs["timeout"]
    for value in timeout.as_dict().values():
        assert_that(value is not None and value <= 5, equal_to(True))


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_transient_statuses_are_retryable(status):
    with (
        patch("api.infrastructure.posthog.client.httpx.post", return_value=_response(status)),
        pytest.raises(RetryablePostHogException),
    ):
        _client().send_batch(MESSAGES)


@pytest.mark.parametrize("status", [201, 400, 401, 413])
def test_any_other_status_is_terminal(status):
    with (
        patch("api.infrastructure.posthog.client.httpx.post", return_value=_response(status)),
        pytest.raises(TerminalPostHogException),
    ):
        _client().send_batch(MESSAGES)


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_transport_failures_are_retryable(error):
    with (
        patch("api.infrastructure.posthog.client.httpx.post", side_effect=error),
        pytest.raises(RetryablePostHogException),
    ):
        _client().send_batch(MESSAGES)


@pytest.mark.parametrize("url", [f"{HOST}/batch/", "https://us.i.posthog.com/batch/"])
def test_guard_blocks_posthog_urls(url):
    calls = []
    guard = make_posthog_blocking_post(lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(RuntimeError):
        guard(url, json={})
    assert_that(calls, equal_to([]))


@pytest.mark.parametrize("as_keyword", [False, True])
def test_guard_delegates_other_urls(as_keyword):
    guard = make_posthog_blocking_post(lambda *args, **kwargs: "delegated")
    url = "http://host.k3d.internal:8765/batch/"

    result = guard(url=url) if as_keyword else guard(url)

    assert_that(result, equal_to("delegated"))


def test_the_token_never_reaches_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with (
        patch("api.infrastructure.posthog.client.httpx.post", return_value=_response(400, text="bad request")),
        pytest.raises(TerminalPostHogException) as raised,
    ):
        _client().send_batch(MESSAGES)

    assert_that(str(raised.value), is_not(contains_string(TOKEN)))
    assert_that(caplog.text, is_not(contains_string(TOKEN)))
