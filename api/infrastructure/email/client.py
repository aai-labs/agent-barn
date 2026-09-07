import base64
import logging
import os
import random
import time
from dataclasses import dataclass
from email.utils import formataddr
from functools import lru_cache

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
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

_CONNECT_TIMEOUT, _READ_TIMEOUT, _WRITE_TIMEOUT, _POOL_TIMEOUT = 5.0, 10.0, 10.0, 5.0
_TOTAL_BUDGET_SECONDS = 30.0
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.5)
# Beyond this, waiting out a Retry-After would hold a worker longer than it is worth;
# fail retryably instead and let the caller's framework reschedule.
_MAX_RETRY_AFTER_SECONDS = 5.0
_ERROR_BODY_LOG_LIMIT = 500


@lru_cache(maxsize=1)
def _load_logo_bytes() -> bytes:
    with open(_LOGO_PATH, "rb") as f:
        return f.read()


def _timeout_for(remaining: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=min(_CONNECT_TIMEOUT, remaining),
        read=min(_READ_TIMEOUT, remaining),
        write=min(_WRITE_TIMEOUT, remaining),
        pool=min(_POOL_TIMEOUT, remaining),
    )


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header, or None when absent/HTTP-date form."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


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
            raise TerminalEmailSendingException(
                "Email delivery is disabled: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN and "
                "SENDER_EMAIL must all be set.",
                email=email.to_email,
            )

        url = _SEND_URL.format(account_id=account_id)
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(email, sender_email)

        # All retry state stays local to the call — this client is a singleton shared
        # across request threads, so instance attributes here would be a real race.
        last_error = "no attempt completed"
        deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_error = f"{last_error} (budget of {_TOTAL_BUDGET_SECONDS}s exhausted)"
                break

            delay: float | None = None
            try:
                response = httpx.post(url, headers=headers, json=payload, timeout=_timeout_for(remaining))
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = f"{type(e).__name__}: {e}"
            else:
                status = response.status_code
                if status < 400:
                    self._verify_accepted(response, email)
                    return email

                body = response.text[:_ERROR_BODY_LOG_LIMIT]
                if status != 429 and status < 500:
                    # 400/401/403 and friends never succeed on retry.
                    self._log_failure(email, f"HTTP {status}", body)
                    raise TerminalEmailSendingException(
                        f"Cloudflare rejected the message (HTTP {status}): {body}",
                        email=email.to_email,
                    )

                last_error = f"HTTP {status}: {body}"
                retry_after = _parse_retry_after(response)
                if retry_after is not None:
                    if retry_after > _MAX_RETRY_AFTER_SECONDS:
                        self._log_failure(email, f"HTTP {status}", f"Retry-After {retry_after}s exceeds budget")
                        raise RetryableEmailSendingException(
                            f"Cloudflare asked to wait {retry_after}s, beyond the in-request budget",
                            email=email.to_email,
                        )
                    delay = retry_after

            if attempt == _MAX_ATTEMPTS:
                break

            if delay is None:
                base = _BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)]
                delay = base * random.uniform(0.8, 1.2)
            if time.monotonic() + delay >= deadline:
                last_error = f"{last_error} (no budget left to retry)"
                break
            time.sleep(delay)

        self._log_failure(email, "exhausted retries", last_error)
        raise RetryableEmailSendingException(
            f"Unable to send email to {email.to_email} after {_MAX_ATTEMPTS} attempts: {last_error}",
            email=email.to_email,
        )

    def _verify_accepted(self, response: httpx.Response, email: Email) -> None:
        """Cloudflare answers with the v4 envelope, so a 2xx alone does not mean accepted:
        `success: false` and `permanent_bounces` both arrive over a successful HTTP call."""
        try:
            body = response.json()
        except ValueError:
            snippet = response.text[:_ERROR_BODY_LOG_LIMIT]
            self._log_failure(email, "non-JSON response body", snippet)
            raise TerminalEmailSendingException(f"Cloudflare returned a non-JSON body: {snippet}", email=email.to_email)

        if not isinstance(body, dict) or not body.get("success"):
            errors = body.get("errors") if isinstance(body, dict) else None
            detail = (
                "; ".join(f"{e.get('code')}: {e.get('message')}" for e in (errors or []) if isinstance(e, dict))
                or response.text[:_ERROR_BODY_LOG_LIMIT]
            )
            self._log_failure(email, "envelope reported failure", detail)
            raise TerminalEmailSendingException(f"Cloudflare rejected the message: {detail}", email=email.to_email)

        # `result` is null on failure, so never index it unguarded.
        result = body.get("result")
        if not isinstance(result, dict):
            result = {}

        if email.to_email in (result.get("permanent_bounces") or []):
            self._log_failure(email, "permanent bounce", "recipient rejected by the receiving server")
            raise TerminalEmailSendingException(
                f"Cloudflare permanently bounced {email.to_email}", email=email.to_email
            )

        accepted = (result.get("delivered") or []) + (result.get("queued") or [])
        if email.to_email not in accepted:
            # Treated as sent on purpose: escalating an unrecognised-but-successful shape
            # would cause duplicate mail on any future response change. This warning is the
            # tripwire if Cloudflare's envelope ever shifts.
            logger.warning(
                "Email accepted but recipient absent from delivered/queued: integration=%s recipient=%s result=%s",
                "email",
                email.to_email,
                result,
            )

    def _log_failure(self, email: Email, reason: str, detail: str) -> None:
        # Log the status and body only — the request headers carry the API token.
        logger.error(
            "Email send failed: integration=%s action=%s recipient=%s subject=%s reason=%s error_detail=%s",
            "email",
            "send",
            email.to_email,
            email.subject,
            reason,
            detail,
        )

    def _build_payload(self, email: Email, sender_email: str) -> dict:
        payload: dict = {
            "from": formataddr((email.from_name, email.from_email or sender_email)),
            "to": email.to_email,
            "subject": email.subject,
        }

        if email.html_part:
            payload["html"] = email.html_part
        if email.text_part:
            payload["text"] = email.text_part
        if email.reply_to:
            payload["reply_to"] = email.reply_to
        if email.headers:
            payload["headers"] = dict(email.headers)

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
