import logging
import smtplib
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from injector import inject, singleton

from api.infrastructure.email.models import Email
from api.core.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


@singleton
@inject
@dataclass
class EmailClient:
    config: Config

    def send(self, email: Email) -> Email:
        last_exception: Exception | None = None
        strategies: list[tuple[Callable[[], smtplib.SMTP], bool]] = [
            (
                lambda: smtplib.SMTP_SSL(self.config.email_smtp_server, port=465),
                False,
            ),
            (lambda: smtplib.SMTP(self.config.email_smtp_server), True),
        ]

        acc_email, acc_password = self.config.email_server_credential.split(":")

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
            exc_info=(
                (type(last_exception), last_exception, last_exception.__traceback__)
                if last_exception
                else None
            ),
        )
        raise exc

    def _build_message(self, email: Email, from_email: str) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = formataddr((email.from_name, from_email))
        msg["To"] = email.to_email
        msg["Subject"] = email.subject
        msg.attach(MIMEText(email.html_part, "html"))
        return msg
