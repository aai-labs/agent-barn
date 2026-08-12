"""Transport behavior for the Cloudflare Email Sending client.

Two things matter beyond the happy path. Cloudflare answers with the v4 envelope, so a
`200` does not mean the message was accepted — `success: false` and `permanent_bounces`
both arrive over a successful HTTP call. And failures must be classified: only 429/5xx and
transport errors are worth retrying, everything else is terminal.
"""

import base64
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import httpx
import pytest
from hamcrest import (
    assert_that,
    calling,
    contains_string,
    equal_to,
    greater_than,
    has_entries,
    has_length,
    is_not,
    less_than,
    raises,
)

from api.core.config import Config
from api.infrastructure.email.client import (
    LOGO_CONTENT_ID,
    EmailClient,
)
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.models import Email

ACCOUNT_ID = "acct-123"
API_TOKEN = "tok-secret-abc"
SENDER = "noreply@mail.agentbarn.dev"
RECIPIENT = "a@example.com"
SEND_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/email/sending/send"


def _client(**overrides) -> EmailClient:
    values = {
        "cloudflare_account_id": ACCOUNT_ID,
        "cloudflare_api_token": API_TOKEN,
        "sender_email": SENDER,
    }
    values.update(overrides)
    return EmailClient(config=cast(Config, SimpleNamespace(**values)))


def _email(html: str = "<p>no logo here</p>") -> Email:
    return Email(to_email=RECIPIENT, subject="Hi", html_part=html)


def _envelope(delivered=(), queued=(), bounced=()) -> dict:
    return {
        "success": True,
        "errors": [],
        "result": {
            "delivered": list(delivered),
            "permanent_bounces": list(bounced),
            "queued": list(queued),
        },
    }


def _response(status: int = 200, json_body=None, text: str | None = None, headers=None) -> httpx.Response:
    kwargs: dict = {"request": httpx.Request("POST", SEND_URL), "headers": headers or {}}
    if text is not None:
        kwargs["text"] = text
    else:
        kwargs["json"] = _envelope(delivered=[RECIPIENT]) if json_body is None else json_body
    return httpx.Response(status, **kwargs)


# --------------------------------------------------------------------------- payload


def test_build_payload_embeds_logo_as_inline_attachment_when_referenced():
    email = _email(f'<img src="cid:{LOGO_CONTENT_ID}" alt="Agent Barn" />')

    payload = _client()._build_payload(email, SENDER)

    assert_that(payload["attachments"], has_length(1))
    logo = payload["attachments"][0]
    # content_id must match the cid: in the html, and disposition must be inline or the
    # image renders as a download instead of in the body. REST uses snake_case here.
    assert_that(
        logo,
        has_entries(
            {
                "content_id": LOGO_CONTENT_ID,
                "disposition": "inline",
                "type": "image/png",
                "filename": "logo.png",
            }
        ),
    )
    assert_that(base64.b64decode(logo["content"]), is_not(equal_to(b"")))


def test_build_payload_omits_attachments_when_logo_not_referenced():
    payload = _client()._build_payload(_email(), SENDER)

    assert_that("attachments" in payload, equal_to(False))


def test_send_posts_to_account_endpoint_with_bearer_token():
    with patch("api.infrastructure.email.client.httpx.post", return_value=_response()) as post:
        _client().send(_email())

    assert_that(post.call_args.args[0], equal_to(SEND_URL))
    assert_that(post.call_args.kwargs["headers"], has_entries({"Authorization": f"Bearer {API_TOKEN}"}))


def test_send_sets_from_with_display_name_and_sender_address():
    with patch("api.infrastructure.email.client.httpx.post", return_value=_response()) as post:
        _client().send(_email())

    payload = post.call_args.kwargs["json"]
    assert_that(payload["from"], equal_to(f"Agent Barn <{SENDER}>"))
    assert_that(payload["to"], equal_to(RECIPIENT))


@pytest.mark.parametrize("missing", ["cloudflare_account_id", "cloudflare_api_token", "sender_email"])
def test_send_raises_terminal_without_calling_out_when_config_missing(missing):
    client = _client(**{missing: ""})

    with patch("api.infrastructure.email.client.httpx.post") as post:
        assert_that(
            calling(client.send).with_args(_email()),
            raises(TerminalEmailSendingException),
        )
        post.assert_not_called()


# ------------------------------------------------------------------- envelope checks


def test_send_accepts_delivered_recipient():
    with patch("api.infrastructure.email.client.httpx.post", return_value=_response()):
        assert_that(_client().send(_email()).to_email, equal_to(RECIPIENT))


def test_send_accepts_queued_recipient():
    body = _envelope(queued=[RECIPIENT])

    with patch("api.infrastructure.email.client.httpx.post", return_value=_response(json_body=body)):
        assert_that(_client().send(_email()).to_email, equal_to(RECIPIENT))


def test_send_raises_terminal_when_envelope_reports_failure_on_http_200():
    # The failure mode that matters most: Cloudflare's v4 envelope can carry success:false
    # over a 200, so the HTTP status alone would report a lost email as sent.
    body = {"success": False, "errors": [{"code": 1000, "message": "Sender domain not verified"}], "result": None}

    with patch("api.infrastructure.email.client.httpx.post", return_value=_response(json_body=body)):
        with patch("api.infrastructure.email.client.logger") as log:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(TerminalEmailSendingException),
            )

    logged = " ".join(str(a) for a in log.error.call_args.args)
    assert_that(logged, contains_string("Sender domain not verified"))
    assert_that(logged, contains_string("1000"))


def test_send_raises_terminal_when_recipient_permanently_bounced():
    body = _envelope(bounced=[RECIPIENT])

    with patch("api.infrastructure.email.client.httpx.post", return_value=_response(json_body=body)):
        assert_that(
            calling(_client().send).with_args(_email()),
            raises(TerminalEmailSendingException),
        )


def test_send_raises_terminal_on_non_json_body():
    # A proxy or gateway can answer 200 with an HTML error page.
    response = _response(text="<html>502 upstream</html>")

    with patch("api.infrastructure.email.client.httpx.post", return_value=response):
        with patch("api.infrastructure.email.client.logger") as log:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(TerminalEmailSendingException),
            )

    assert_that(" ".join(str(a) for a in log.error.call_args.args), contains_string("502 upstream"))


def test_send_treats_absent_recipient_as_sent_but_warns():
    # Deliberate: escalating an unrecognised-but-successful shape would cause duplicate
    # mail on any future API change. Warn instead of failing open into a retry storm.
    body = _envelope(delivered=["someone-else@example.com"])

    with patch("api.infrastructure.email.client.httpx.post", return_value=_response(json_body=body)):
        with patch("api.infrastructure.email.client.logger") as log:
            _client().send(_email())

    log.warning.assert_called_once()


def test_send_survives_null_result_without_crashing():
    body = {"success": False, "errors": [], "result": None}

    with patch("api.infrastructure.email.client.httpx.post", return_value=_response(json_body=body)):
        assert_that(
            calling(_client().send).with_args(_email()),
            raises(TerminalEmailSendingException),
        )


# ----------------------------------------------------------- classification & retry


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_terminal_and_never_retried(status):
    response = _response(status, text="rejected")

    with patch("api.infrastructure.email.client.httpx.post", return_value=response) as post:
        with patch("api.infrastructure.email.client.time.sleep") as sleep:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(TerminalEmailSendingException),
            )

    assert_that(post.call_count, equal_to(1))
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transient_statuses_are_retried_then_raise_retryable(status):
    response = _response(status, text="try later")

    with patch("api.infrastructure.email.client.httpx.post", return_value=response) as post:
        with patch("api.infrastructure.email.client.time.sleep"):
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(RetryableEmailSendingException),
            )

    assert_that(post.call_count, equal_to(3))


def test_send_recovers_when_a_retry_succeeds():
    responses = [_response(429, text="slow down"), _response()]

    with patch("api.infrastructure.email.client.httpx.post", side_effect=responses) as post:
        with patch("api.infrastructure.email.client.time.sleep"):
            _client().send(_email())

    assert_that(post.call_count, equal_to(2))


@pytest.mark.parametrize("exc", [httpx.TimeoutException("timed out"), httpx.ConnectError("refused")])
def test_transport_failures_are_retryable(exc):
    with patch("api.infrastructure.email.client.httpx.post", side_effect=exc) as post:
        with patch("api.infrastructure.email.client.time.sleep"):
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(RetryableEmailSendingException),
            )

    assert_that(post.call_count, equal_to(3))


def test_short_retry_after_is_honoured():
    responses = [_response(429, text="slow", headers={"Retry-After": "2"}), _response()]

    with patch("api.infrastructure.email.client.httpx.post", side_effect=responses):
        with patch("api.infrastructure.email.client.time.sleep") as sleep:
            _client().send(_email())

    assert_that(sleep.call_args.args[0], equal_to(2.0))


def test_long_retry_after_gives_up_immediately_instead_of_sleeping():
    # Sleeping through a long Retry-After would pin a threadpool worker; surface a
    # retryable error so the delivery framework reschedules instead.
    response = _response(429, text="slow", headers={"Retry-After": "600"})

    with patch("api.infrastructure.email.client.httpx.post", return_value=response) as post:
        with patch("api.infrastructure.email.client.time.sleep") as sleep:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(RetryableEmailSendingException),
            )

    assert_that(post.call_count, equal_to(1))
    sleep.assert_not_called()


def test_total_backoff_stays_within_budget():
    response = _response(500, text="boom")

    with patch("api.infrastructure.email.client.httpx.post", return_value=response):
        with patch("api.infrastructure.email.client.time.sleep") as sleep:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(RetryableEmailSendingException),
            )

    total = sum(call.args[0] for call in sleep.call_args_list)
    assert_that(total, greater_than(0))
    assert_that(total, less_than(5))


def test_failure_logs_response_body_without_leaking_token():
    response = _response(403, text="sending domain not verified")

    with patch("api.infrastructure.email.client.httpx.post", return_value=response):
        with patch("api.infrastructure.email.client.logger") as log:
            assert_that(
                calling(_client().send).with_args(_email()),
                raises(TerminalEmailSendingException),
            )

    logged = " ".join(str(a) for a in log.error.call_args.args)
    assert_that(logged, contains_string("sending domain not verified"))
    assert_that(logged, is_not(contains_string(API_TOKEN)))
