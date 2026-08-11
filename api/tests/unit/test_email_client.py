"""Transport behavior for the Cloudflare Email Sending client: payload shape, auth, and
failure signalling. `send` must raise on failure — `EmailService` catches that and returns
`False`, which is what drives the agent-lifecycle handler's retry."""

import base64
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import httpx
import pytest
from hamcrest import (
    assert_that,
    calling,
    contains_string,
    equal_to,
    has_entries,
    has_length,
    is_not,
    raises,
)

from api.core.config import Config
from api.infrastructure.email.client import LOGO_CONTENT_ID, EmailClient
from api.infrastructure.email.models import Email

ACCOUNT_ID = "acct-123"
API_TOKEN = "tok-secret-abc"
SENDER = "noreply@mail.agentbarn.dev"
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
    return Email(to_email="a@example.com", subject="Hi", html_part=html)


def test_build_payload_embeds_logo_as_inline_attachment_when_referenced():
    email = _email(f'<img src="cid:{LOGO_CONTENT_ID}" alt="Agent Barn" />')

    payload = _client()._build_payload(email, SENDER)

    assert_that(payload["attachments"], has_length(1))
    logo = payload["attachments"][0]
    # content_id must match the cid: referenced in the html, and disposition must be
    # inline or the image renders as a download rather than in the body.
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
    with patch("api.infrastructure.email.client.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)

        _client().send(_email())

    assert_that(post.call_args.args[0], equal_to(SEND_URL))
    assert_that(
        post.call_args.kwargs["headers"],
        has_entries({"Authorization": f"Bearer {API_TOKEN}"}),
    )


def test_send_sets_from_with_display_name_and_sender_address():
    with patch("api.infrastructure.email.client.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)

        _client().send(_email())

    payload = post.call_args.kwargs["json"]
    assert_that(payload["from"], equal_to(f"Agent Barn <{SENDER}>"))
    assert_that(payload["to"], equal_to("a@example.com"))


@pytest.mark.parametrize(
    "missing",
    ["cloudflare_account_id", "cloudflare_api_token", "sender_email"],
)
def test_send_raises_without_calling_out_when_config_missing(missing):
    client = _client(**{missing: ""})

    with patch("api.infrastructure.email.client.httpx.post") as post:
        assert_that(calling(client.send).with_args(_email()), raises(RuntimeError))

        post.assert_not_called()


def test_send_raises_and_logs_response_body_without_leaking_token():
    # Cloudflare returns the actionable reason in the body (e.g. unverified sending
    # domain); the status code alone can't distinguish the failure modes.
    response = httpx.Response(
        403,
        text="sending domain not verified",
        request=httpx.Request("POST", SEND_URL),
    )

    with patch("api.infrastructure.email.client.httpx.post", return_value=response):
        with patch("api.infrastructure.email.client.logger") as log:
            assert_that(calling(_client().send).with_args(_email()), raises(RuntimeError))

    logged = " ".join(str(arg) for arg in log.error.call_args.args)
    assert_that(logged, contains_string("sending domain not verified"))
    assert_that(logged, is_not(contains_string(API_TOKEN)))
