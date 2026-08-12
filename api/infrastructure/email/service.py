import logging
import os
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject, singleton
from jinja2 import Template
from mjml import mjml_to_html

from api.core.config import Config
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.exceptions import (
    EmailRenderingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.models import Email, EmailTemplate, EmailTemplateAttribute

logger = logging.getLogger(__name__)


@singleton
@inject
@dataclass
class EmailService:
    config: Config
    client: EmailClient

    def _email_enabled_or_log(self, action: str, receiver_email: str) -> bool:
        if self.config.is_email_delivery_enabled:
            return True

        logger.error(
            "Email delivery is disabled: action=%s recipient=%s reason=%s",
            action,
            receiver_email,
            "CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN or SENDER_EMAIL is missing",
        )
        return False

    def create_email(self, email_template: EmailTemplate) -> Email:
        mjml_template = read_template(email_template.file_name)
        # autoescape so user-supplied values (user_name from owner_name/full_name) can't
        # inject markup into the email body. URLs are the only other injected values and
        # HTML-escaping them (& -> &amp;) is correct inside href attributes.
        template = Template(mjml_template, autoescape=True)

        data = {}
        for attribute in email_template.attributes:
            data[attribute.name] = attribute.value
        data["current_year"] = datetime.now(UTC).year

        mjml = template.render(data)
        html = self.render(mjml=mjml)

        return Email(
            to_email=email_template.receiver_email,
            subject=email_template.subject,
            html_part=html,
            from_name=self.config.email_from_name,
        )

    def render(self, mjml):
        try:
            result = mjml_to_html(mjml)
        except Exception:
            raise EmailRenderingException("MJML rendering failed", email="")

        return result.html

    def send(self, email: Email):
        if not self._email_enabled_or_log(action="send", receiver_email=email.to_email):
            return False

        try:
            self.client.send(email)
            return True
        except Exception:
            msg = "Unable to send email"
            logger.error(f"{msg} : {traceback.format_exc()}")
            return False

    def send_password_reset_email(
        self,
        receiver_email: str,
        password_reset_link: str,
        receiver_name: str | None = None,
    ):
        if not self._email_enabled_or_log(
            action="send_password_reset_email",
            receiver_email=receiver_email,
        ):
            return False

        try:
            email_template = EmailTemplate(
                file_name="password-reset-template.mjml",
                subject="Reset your password",
                receiver_name=receiver_name,
                receiver_email=receiver_email,
                attributes=[
                    EmailTemplateAttribute(
                        name="user_name",
                        value=receiver_name or receiver_email,
                    ),
                    EmailTemplateAttribute(
                        name="password_reset_link",
                        value=password_reset_link,
                    ),
                ],
            )

            email = self.create_email(email_template)
            self.client.send(email)
            return True
        except Exception:
            msg = f"Unable to send password reset email to {receiver_email}"
            logger.error(f"{msg} : {traceback.format_exc()}")
            return False

    def send_user_invite_email(
        self,
        receiver_email: str,
        set_password_link: str,
        receiver_name: str | None = None,
    ):
        if not self._email_enabled_or_log(
            action="send_user_invite_email",
            receiver_email=receiver_email,
        ):
            return False

        try:
            email_template = EmailTemplate(
                file_name="user-invite-template.mjml",
                subject="You are invited!",
                receiver_name=receiver_name,
                receiver_email=receiver_email,
                attributes=[
                    EmailTemplateAttribute(
                        name="user_name",
                        value=receiver_name or receiver_email,
                    ),
                    EmailTemplateAttribute(
                        name="set_password_link",
                        value=set_password_link,
                    ),
                ],
            )

            email = self.create_email(email_template)
            self.client.send(email)
            return True
        except Exception:
            msg = f"Unable to send account invite email to {receiver_email}"
            logger.error(f"{msg} : {traceback.format_exc()}")
            return False

    def send_email_verification_email(
        self,
        receiver_email: str,
        verification_link: str,
        receiver_name: str | None = None,
    ):
        if not self._email_enabled_or_log(
            action="send_email_verification_email",
            receiver_email=receiver_email,
        ):
            return False

        try:
            email_template = EmailTemplate(
                file_name="email-verification-template.mjml",
                subject="Verify your email",
                receiver_name=receiver_name,
                receiver_email=receiver_email,
                attributes=[
                    EmailTemplateAttribute(
                        name="user_name",
                        value=receiver_name or receiver_email,
                    ),
                    EmailTemplateAttribute(
                        name="verification_link",
                        value=verification_link,
                    ),
                ],
            )

            email = self.create_email(email_template)
            self.client.send(email)
            return True
        except Exception:
            msg = f"Unable to send verification email to {receiver_email}"
            logger.error(f"{msg} : {traceback.format_exc()}")
            return False

    def send_agent_lifecycle_email(
        self,
        *,
        receiver_email: str,
        receiver_name: str | None,
        agent_name: str,
        lifecycle_action: str,
    ) -> None:
        """Unlike the other send methods this propagates `EmailSendingException` rather than
        swallowing it. `AgentLifecycleEmailHandler` runs under the delivery framework and
        needs the retryable/terminal distinction to pick its retry behaviour; collapsing
        every failure to `False` made it retry payload errors that can never succeed."""
        if not self._email_enabled_or_log(
            action="send_agent_lifecycle_email",
            receiver_email=receiver_email,
        ):
            # Delivery disabled is a documented no-op (see helm values.yaml), not a failure.
            # Raising here would dead-letter every lifecycle event on mail-less environments.
            return

        email_template = EmailTemplate(
            file_name="agent-lifecycle-template.mjml",
            subject=f"Agent {agent_name} {lifecycle_action}",
            receiver_name=receiver_name,
            receiver_email=receiver_email,
            attributes=[
                EmailTemplateAttribute(name="user_name", value=receiver_name or receiver_email),
                EmailTemplateAttribute(name="agent_name", value=agent_name),
                EmailTemplateAttribute(name="lifecycle_action", value=lifecycle_action),
            ],
        )
        try:
            email = self.create_email(email_template)
        except EmailRenderingException as e:
            # A template that won't render won't render on retry either.
            logger.error(f"Unable to render agent lifecycle email for {receiver_email} : {traceback.format_exc()}")
            raise TerminalEmailSendingException(str(e), email=receiver_email) from e

        self.client.send(email)

    def send_user_deletion_email(
        self,
        receiver_email: str,
        receiver_name: str | None = None,
    ):
        if not self._email_enabled_or_log(
            action="send_user_deletion_email",
            receiver_email=receiver_email,
        ):
            return False

        try:
            email_template = EmailTemplate(
                file_name="user-deletion-template.mjml",
                subject="Your account has been deleted.",
                receiver_name=receiver_name,
                receiver_email=receiver_email,
                attributes=[
                    EmailTemplateAttribute(
                        name="user_name",
                        value=receiver_name or receiver_email,
                    ),
                ],
            )

            email = self.create_email(email_template)
            self.client.send(email)
            return True
        except Exception:
            msg = f"Unable to send account deletion email to {receiver_email}"
            logger.error(f"{msg} : {traceback.format_exc()}")
            return False


def read_template(template_filename):
    filename = os.path.join(
        os.path.dirname(__file__),
        "templates",
        template_filename,
    )

    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()
        return content
