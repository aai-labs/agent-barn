"""Gmail with an app password, answered by the credential gateway itself.

The agent sends aai-cli Custom API requests; the plugin turns exactly two of them into
read-only inbox reads and refuses everything else before Gmail is ever contacted.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.models import GmailAppPasswordContent
from api.domains.integrations.plugins.base import ServedRequest
from api.domains.integrations.plugins.providers import GMAIL_SERVED_BASE_URL, GmailAppPasswordPlugin
from api.infrastructure.google.gmail_imap import (
    GmailInbox,
    InvalidMailQuery,
    MailMessage,
    MailNotFound,
    MailSignInFailed,
    MailSummary,
    MailUnavailable,
)

_CONTENT = GmailAppPasswordContent(email="someone@gmail.com", app_password="abcd efgh ijkl mnop")
_PASSWORD = "abcdefghijklmnop"
_SUMMARY = MailSummary(id="3753", sender="Google <no-reply@accounts.google.com>", subject="Security alert", date="d")
_MESSAGE = MailMessage(
    id="3753",
    sender=_SUMMARY.sender,
    to="someone@gmail.com",
    cc="",
    subject="Security alert",
    date="d",
    body="An app password was created.",
    truncated=False,
    attachments=["notice.pdf"],
)


def _plugin() -> tuple[GmailAppPasswordPlugin, Any]:
    plugin = GmailAppPasswordPlugin()
    inbox: Any = MagicMock(spec=GmailInbox)
    inbox.list_messages.return_value = [_SUMMARY]
    inbox.get_message.return_value = _MESSAGE
    plugin.inbox = inbox
    return plugin, inbox


def _get(path: str, query: dict[str, Any] | None = None) -> ServedRequest:
    return ServedRequest("GET", f"{GMAIL_SERVED_BASE_URL}{path}", query or {})


def test_listing_returns_message_headers_newest_first():
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, _get("/messages", {"q": "from:google", "limit": "5"}))

    assert_that(response.status, equal_to(200))
    assert_that(
        response.body,
        equal_to({"messages": [{"id": "3753", "sender": _SUMMARY.sender, "subject": "Security alert", "date": "d"}]}),
    )
    inbox.list_messages.assert_called_once_with("someone@gmail.com", _PASSWORD, query="from:google", limit=5)


def test_listing_without_a_search_uses_the_default_limit():
    plugin, inbox = _plugin()

    plugin.serve(_CONTENT, _get("/messages"))

    inbox.list_messages.assert_called_once_with("someone@gmail.com", _PASSWORD, query=None, limit=20)


def test_a_json_number_limit_is_accepted():
    # A complete request object from aai-cli may carry {"limit": 10} rather than a string.
    plugin, inbox = _plugin()

    plugin.serve(_CONTENT, _get("/messages", {"limit": 10}))

    inbox.list_messages.assert_called_once_with("someone@gmail.com", _PASSWORD, query=None, limit=10)


def test_a_search_written_into_the_url_is_honoured():
    plugin, inbox = _plugin()

    plugin.serve(_CONTENT, _get("/messages?q=is%3Aunread&limit=3"))

    inbox.list_messages.assert_called_once_with("someone@gmail.com", _PASSWORD, query="is:unread", limit=3)


def test_reading_returns_the_message_text_and_attachment_names():
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, _get("/messages/3753"))

    assert_that(response.status, equal_to(200))
    assert_that(response.body["body"], equal_to("An app password was created."))
    assert_that(response.body["attachments"], equal_to(["notice.pdf"]))
    assert_that(response.body["to"], equal_to("someone@gmail.com"))
    inbox.get_message.assert_called_once_with("someone@gmail.com", _PASSWORD, "3753")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_anything_but_a_read_is_refused_before_gmail_is_contacted(method):
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, ServedRequest(method, f"{GMAIL_SERVED_BASE_URL}/messages/3753"))

    assert_that(response.status, equal_to(405))
    assert_that(response.body["error"], equal_to("read_only"))
    assert_that(inbox.method_calls, equal_to([]))


@pytest.mark.parametrize(
    "url",
    [
        f"{GMAIL_SERVED_BASE_URL}/messages/3753/delete",
        f"{GMAIL_SERVED_BASE_URL}/messages/abc",
        f"{GMAIL_SERVED_BASE_URL}/messages/\u0661\u0662",
        f"{GMAIL_SERVED_BASE_URL}/messages/{'1' * 21}",
        f"{GMAIL_SERVED_BASE_URL}/send",
        f"{GMAIL_SERVED_BASE_URL}",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        "http://gmail.internal/v1/messages",
        "https://gmail.internal.evil.example/v1/messages",
    ],
)
def test_an_unknown_address_is_not_found(url):
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, ServedRequest("GET", url))

    assert_that(response.status, equal_to(404))
    assert_that(response.body["error"], equal_to("not_found"))
    assert_that(inbox.method_calls, equal_to([]))


@pytest.mark.parametrize(
    "query",
    [
        {"limit": "0"},
        {"limit": "51"},
        {"limit": "ten"},
        {"limit": True},
        {"limit": "\u00b2"},
        {"limit": "9" * 5000},
        {"limit": 5.0},
        {"q": ["a", "b"]},
        {"label": "INBOX"},
    ],
)
def test_a_bad_listing_query_is_refused(query):
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, _get("/messages", query))

    assert_that(response.status, equal_to(400))
    assert_that(response.body["error"], equal_to("invalid_request"))
    assert_that(inbox.method_calls, equal_to([]))


def test_a_query_on_a_single_message_is_refused():
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, _get("/messages/3753", {"limit": "1"}))

    assert_that(response.status, equal_to(400))
    assert_that(inbox.method_calls, equal_to([]))


def test_a_request_body_is_refused():
    plugin, inbox = _plugin()

    response = plugin.serve(_CONTENT, ServedRequest("GET", f"{GMAIL_SERVED_BASE_URL}/messages", {}, {"x": 1}))

    assert_that(response.status, equal_to(400))
    assert_that(inbox.method_calls, equal_to([]))


@pytest.mark.parametrize(
    "failure,status,error",
    [
        (InvalidMailQuery("bad"), 400, "invalid_query"),
        (MailNotFound("9"), 404, "not_found"),
        (MailSignInFailed(), 502, "mail_sign_in_failed"),
        (MailUnavailable("down"), 502, "upstream_unreachable"),
    ],
)
def test_gmail_failures_become_a_status_the_agent_can_read(failure, status, error):
    plugin, inbox = _plugin()
    inbox.list_messages.side_effect = failure

    response = plugin.serve(_CONTENT, _get("/messages"))

    assert_that(response.status, equal_to(status))
    assert_that(response.body["error"], equal_to(error))
    assert_that(_PASSWORD in str(response.body), equal_to(False))


def test_the_gateway_profile_holds_no_credential_and_points_at_the_gateway():
    block = GmailAppPasswordPlugin().aai_cli_gateway_profile_block(
        _CONTENT, base_url="http://gateway/gateway/v1/served/request", token_env="AF_GATEWAY_TOKEN_X"
    )

    assert_that(
        block,
        equal_to(
            "[profiles.gmail-inbox]\n"
            'provider = "custom_api"\n'
            f'base_url = "{GMAIL_SERVED_BASE_URL}"\n'
            'gateway_url = "http://gateway/gateway/v1/served/request"\n'
            'gateway_token_env = "AF_GATEWAY_TOKEN_X"\n'
        ),
    )
    for credential in ("someone@gmail.com", "abcd", _PASSWORD, "auth_type", "token_secret"):
        assert_that(credential in block, equal_to(False))


def test_the_agent_is_told_the_two_exact_commands():
    capability = GmailAppPasswordPlugin().aai_cli_capability_for(_CONTENT)

    assert_that(capability is not None and f"--url {GMAIL_SERVED_BASE_URL}/messages" in capability, equal_to(True))
    assert_that(f"--url {GMAIL_SERVED_BASE_URL}/messages/<id>" in str(capability), equal_to(True))
    assert_that("--query q=" in str(capability), equal_to(True))
    for forbidden in ("curl", "AF_GATEWAY", "Authorization", "Bearer", "$"):
        assert_that(forbidden in str(capability), equal_to(False))


def test_the_tools_context_names_the_mailbox_as_read_only():
    line = GmailAppPasswordPlugin().aai_cli_context_line(_CONTENT)

    assert_that(line, equal_to("- **Gmail** (`gmail-inbox`): inbox of someone@gmail.com (read-only)"))
