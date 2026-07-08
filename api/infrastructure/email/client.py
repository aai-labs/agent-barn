import logging
import os
import smtplib
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from functools import lru_cache

from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.email.logging_utils import (
    log_email_delivery_disabled_warning,
)
from api.infrastructure.email.models import Email

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())

# The brand mark is the same barn logo as the web app's navbar/favicon. Email clients
# strip inline <svg>, so templates reference `cid:LOGO_CONTENT_ID` and we attach the
# rasterised PNG inline (multipart/related) whenever a template asks for it.
LOGO_CONTENT_ID = "agent-barn-logo"
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")


@lru_cache(maxsize=1)
def _load_logo_bytes() -> bytes:
    with open(_LOGO_PATH, "rb") as f:
        return f.read()


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
            raise RuntimeError(
                "Invalid EMAIL_SERVER_CREDENTIAL format. Expected '<email>:<password>'."
            )

        acc_email, acc_password = credential.split(":", 1)
        if not acc_email or not acc_password:
            raise RuntimeError(
                "Invalid EMAIL_SERVER_CREDENTIAL value. Email and password are both required."
            )

        # The visible "From" address may differ from the SMTP login (e.g. sending as
        # no-reply@agentbarn.dev while authenticating with an admin-provided account).
        # The envelope sender / SMTP login stay the authenticated account.
        from_address = (self.config.email_from_address or "").strip() or acc_email

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
                    msg = self._build_message(email, from_address)
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
        # multipart/related lets the html reference the logo via `cid:` so it renders
        # inline (no external hosting, not gated behind "display images").
        msg = MIMEMultipart("related")
        msg["From"] = formataddr((email.from_name, from_email))
        msg["To"] = email.to_email
        msg["Subject"] = email.subject
        msg.attach(MIMEText(email.html_part, "html"))

        if f"cid:{LOGO_CONTENT_ID}" in email.html_part:
            logo = MIMEImage(_load_logo_bytes(), _subtype="png")
            logo.add_header("Content-ID", f"<{LOGO_CONTENT_ID}>")
            logo.add_header("Content-Disposition", "inline", filename="logo.png")
            msg.attach(logo)

        return msg
