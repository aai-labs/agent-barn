from __future__ import annotations

import httpx
from hamcrest import assert_that, contains_string, equal_to, has_properties, is_, none, not_
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

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


def test_discord_disallowed_intent_close_is_actionable_without_persisting_reason() -> None:
    error = ConnectionClosedError(Close(4014, "Disallowed intent(s)"), None)

    normalized = normalize_communication_error(error, operation="ingress_session")

    assert_that(normalized.code, equal_to("CONFIGURATION_ERROR"))
    assert_that(
        normalized.summary,
        equal_to(
            "Discord rejected a privileged gateway intent; enable Message Content Intent "
            "in the Discord Developer Portal, then reconnect (4014)"
        ),
    )
    assert_that(
        normalized.details,
        has_properties(
            category=equal_to(CommunicationErrorCategory.CONFIGURATION),
            provider_code=equal_to("4014"),
            retryable=is_(False),
        ),
    )
    assert_that(str(normalized.details), not_(contains_string("Disallowed intent")))


def test_discord_authentication_close_explains_how_to_recover() -> None:
    error = ConnectionClosedError(Close(4004, "Authentication failed"), None)

    normalized = normalize_communication_error(error, operation="ingress_session")

    assert_that(normalized.code, equal_to("AUTHENTICATION_FAILED"))
    assert_that(
        normalized.summary,
        equal_to(
            "Discord rejected the bot token; update this Connection with a valid bot token, then reconnect (4004)"
        ),
    )
    assert_that(
        normalized.details,
        has_properties(
            category=equal_to(CommunicationErrorCategory.AUTHENTICATION),
            provider_code=equal_to("4004"),
            retryable=is_(False),
        ),
    )


def test_discord_invalid_intent_close_explains_how_to_recover() -> None:
    error = ConnectionClosedError(Close(4013, "Invalid intent(s)"), None)

    normalized = normalize_communication_error(error, operation="ingress_session")

    assert_that(normalized.code, equal_to("CONFIGURATION_ERROR"))
    assert_that(
        normalized.summary,
        equal_to(
            "Discord rejected the gateway intent selection; review the configured Discord intents, "
            "then reconnect (4013)"
        ),
    )
