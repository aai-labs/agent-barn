import base64
import logging
import os
from dataclasses import dataclass
from email.utils import formataddr
from functools import lru_cache

import httpx
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
# strip inline <svg>, so templates reference `cid:LOGO_CONTENT_ID` and we ship the
# rasterised PNG as an inline attachment whenever a template asks for it.
LOGO_CONTENT_ID = "agent-barn-logo"
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")

_SEND_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send"
_TIMEOUT = 30


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
        account_id = (self.config.cloudflare_account_id or "").strip()
        api_token = (self.config.cloudflare_api_token or "").strip()
        sender_email = (self.config.sender_email or "").strip()

        if not account_id or not api_token or not sender_email:
            log_email_delivery_disabled_warning(logger)
            raise RuntimeError(
                "Email delivery is disabled: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN and "
                "SENDER_EMAIL must all be set."
            )

        try:
            response = httpx.post(
                _SEND_URL.format(account_id=account_id),
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json=self._build_payload(email, sender_email),
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Cloudflare returns the actionable reason in the body (e.g. the sending
            # domain isn't Verified); the status code alone doesn't distinguish the
            # failure modes. Never log the request headers — they carry the API token.
            logger.error(
                "Email send failed: integration=%s action=%s recipient=%s subject=%s status=%s error_detail=%s",
                "email",
                "send",
                email.to_email,
                email.subject,
                e.response.status_code,
                e.response.text,
            )
            raise RuntimeError(f"Unable to send email to {email.to_email}") from e
        except httpx.HTTPError as e:
            logger.error(
                "Email send failed: integration=%s action=%s recipient=%s subject=%s error_detail=%s",
                "email",
                "send",
                email.to_email,
                email.subject,
                str(e),
            )
            raise RuntimeError(f"Unable to send email to {email.to_email}") from e

        return email

    def _build_payload(self, email: Email, sender_email: str) -> dict:
        payload: dict = {
            "from": formataddr((email.from_name, sender_email)),
            "to": email.to_email,
            "subject": email.subject,
            "html": email.html_part,
        }

        # The JSON API has no multipart/related equivalent, so the logo travels as an
        # inline attachment whose content_id resolves the `cid:` reference in the html.
        # Note the REST field is snake_case `content_id`; `contentId` is Workers-only.
        if f"cid:{LOGO_CONTENT_ID}" in email.html_part:
            payload["attachments"] = [
                {
                    "content": base64.b64encode(_load_logo_bytes()).decode("ascii"),
                    "filename": "logo.png",
                    "type": "image/png",
                    "disposition": "inline",
                    "content_id": LOGO_CONTENT_ID,
                }
            ]

        return payload
