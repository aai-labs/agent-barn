import logging
import smtplib
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.email.logging_utils import (
    log_email_delivery_disabled_warning,
)
from api.infrastructure.email.models import Email

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


@singleton
@inject
@dataclass
class EmailClient:
    config: Config

    def send(self, email: Email) -> Email:
        smtp_server = (self.config.email_smtp_server or "").strip()
        credential = (self.config.email_server_credential or "").strip()

        if not smtp_server or not credential:
            log_email_delivery_disabled_warning(logger)
            raise RuntimeError(
                "Email delivery is disabled: EMAIL_SERVER_CREDENTIAL and EMAIL_SMTP_SERVER must both be set."
            )

        if ":" not in credential:
            raise RuntimeError("Invalid EMAIL_SERVER_CREDENTIAL format. Expected '<email>:<password>'.")

        acc_email, acc_password = credential.split(":", 1)
        if not acc_email or not acc_password:
            raise RuntimeError("Invalid EMAIL_SERVER_CREDENTIAL value. Email and password are both required.")

        last_exception: Exception | None = None
        strategies: list[tuple[Callable[[], smtplib.SMTP], bool]] = [
            (
                lambda: smtplib.SMTP_SSL(smtp_server, port=465),
                False,
            ),
            (lambda: smtplib.SMTP(smtp_server), True),
        ]

        for create_client, use_starttls in strategies:
            try:
                with create_client() as server:
                    if use_starttls:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()

                    server.login(user=acc_email, password=acc_password)
                    msg = self._build_message(email, acc_email)
                    server.sendmail(acc_email, email.to_email, msg.as_string())
                    return email
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Email send attempt with {'STARTTLS' if use_starttls else 'SSL'} failed:\n{traceback.format_exc()}"
                )

        exc = RuntimeError(f"Unable to send email to {email.to_email}")
        logger.error(
            "Email send failed: integration=%s action=%s recipient=%s subject=%s error_detail=%s",
            "email",
            "send",
            email.to_email,
            email.subject,
            f"All SMTP strategies failed for {email.to_email}",
            exc_info=((type(last_exception), last_exception, last_exception.__traceback__) if last_exception else None),
        )
        raise exc

    def _build_message(self, email: Email, from_email: str) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = formataddr((email.from_name, from_email))
        msg["To"] = email.to_email
        msg["Subject"] = email.subject
        msg.attach(MIMEText(email.html_part, "html"))
        return msg
