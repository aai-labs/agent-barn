from __future__ import annotations

import httpx
from hamcrest import assert_that, contains_string, equal_to, has_properties, is_, none, not_

from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import CommunicationErrorCategory


def test_http_failure_keeps_safe_provider_diagnostics_without_the_request_secret() -> None:
    request = httpx.Request(
        "GET",
        "https://api.telegram.org/botsecret-token/getUpdates",
    )
    response = httpx.Response(
        401,
        request=request,
        headers={"x-request-id": "telegram-request-123"},
        json={"ok": False, "error_code": 401, "description": "Unauthorized", "error": "unauthorized"},
    )
    error = httpx.HTTPStatusError("401 Unauthorized for a secret-token URL", request=request, response=response)

    normalized = normalize_communication_error(error, operation="poll_updates")

    assert_that(normalized.code, equal_to("AUTHENTICATION_FAILED"))
    assert_that(
        normalized.summary,
        equal_to("Provider rejected the connection credential (HTTP 401, unauthorized)"),
    )
    assert_that(
        normalized.details,
        has_properties(
            category=equal_to(CommunicationErrorCategory.AUTHENTICATION),
            operation=equal_to("poll_updates"),
            http_status=equal_to(401),
            provider_code=equal_to("unauthorized"),
            retryable=is_(False),
            request_id=equal_to("telegram-request-123"),
        ),
    )
    assert_that(normalized.summary, not_(contains_string("secret-token")))
    assert_that(str(normalized.details), not_(contains_string("secret-token")))


def test_timeout_failure_is_actionable_and_retryable() -> None:
    normalized = normalize_communication_error(TimeoutError("bot-secret timed out"), operation="send_message")

    assert_that(normalized.code, equal_to("TIMEOUT"))
    assert_that(normalized.summary, equal_to("The provider did not respond before the request timed out"))
    assert_that(
        normalized.details,
        has_properties(
            category=equal_to(CommunicationErrorCategory.TIMEOUT),
            operation=equal_to("send_message"),
            retryable=is_(True),
            http_status=none(),
            provider_code=none(),
        ),
    )
    assert_that(str(normalized.details), not_(contains_string("bot-secret")))
