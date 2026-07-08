"""User-supplied names (owner_name / full_name) flow into transactional emails, so they
must be HTML-escaped when rendered — otherwise markup injects into the email body."""

from types import SimpleNamespace
from typing import cast

from hamcrest import assert_that, contains_string, is_not

from api.core.config import Config
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import EmailTemplate, EmailTemplateAttribute
from api.infrastructure.email.service import EmailService


def _service() -> EmailService:
    # create_email only reads config.email_from_name and never touches the client.
    return EmailService(
        config=cast(Config, SimpleNamespace(email_from_name="Agent Barn")),
        client=cast(EmailClient, SimpleNamespace()),
    )


def test_create_email_escapes_user_supplied_name():
    malicious = "<script>alert(1)</script>"
    built = _service().create_email(
        EmailTemplate(
            file_name="user-invite-template.mjml",
            subject="You are invited!",
            receiver_email="victim@example.com",
            receiver_name=None,
            attributes=[
                EmailTemplateAttribute(name="user_name", value=malicious),
                EmailTemplateAttribute(
                    name="set_password_link", value="https://app/set"
                ),
            ],
        )
    )

    assert_that(built.html_part, is_not(contains_string(malicious)))
    assert_that(built.html_part, contains_string("&lt;script&gt;"))
