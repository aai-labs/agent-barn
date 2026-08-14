from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from hamcrest import assert_that, calling, raises

from api.core.config import Config
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.exceptions import TerminalEmailSendingException
from api.infrastructure.email.service import EmailService


def _service() -> EmailService:
    return EmailService(
        config=cast(
            Config,
            SimpleNamespace(email_from_name="Agent Barn", is_email_delivery_enabled=True),
        ),
        client=cast(EmailClient, SimpleNamespace(send=lambda email: email)),
    )


def _send():
    return _service().send_agent_lifecycle_email(
        receiver_email="a@example.com",
        receiver_name="A",
        agent_name="watcher",
        lifecycle_action="started",
    )


def test_missing_template_file_is_terminal():
    with patch(
        "api.infrastructure.email.service.read_template",
        side_effect=FileNotFoundError("agent-lifecycle-template.mjml"),
    ):
        assert_that(calling(_send), raises(TerminalEmailSendingException))


def test_malformed_template_syntax_is_terminal():
    with patch("api.infrastructure.email.service.read_template", return_value="{% if %}"):
        assert_that(calling(_send), raises(TerminalEmailSendingException))


def test_mjml_rendering_failure_is_terminal():
    with patch("api.infrastructure.email.service.mjml_to_html", side_effect=ValueError("bad mjml")):
        assert_that(calling(_send), raises(TerminalEmailSendingException))
