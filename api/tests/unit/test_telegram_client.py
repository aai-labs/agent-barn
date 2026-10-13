from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to

from api.infrastructure.telegram.client import validate_bot_token


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            {"ok": True, "result": {"id": 17, "username": "native_bot"}},
            (True, "", {"id": 17, "username": "native_bot"}),
        ),
        ({"ok": False, "description": "invalid"}, (False, "Telegram bot token is invalid: invalid", {})),
    ],
)
def test_validation_preserves_provider_identity_and_failure_reason(body, expected):
    response = MagicMock(status_code=200)
    response.json.return_value = body
    with (
        patch(
            "api.infrastructure.telegram.client.get_config",
            return_value=MagicMock(skip_telegram_token_validation=False),
        ),
        patch("api.infrastructure.telegram.client.resilient_request", return_value=response) as request,
    ):
        assert_that(validate_bot_token("test-bot"), equal_to(expected))
        assert_that(request.call_args.args, equal_to(("GET", "https://api.telegram.org/bottest-bot/getMe")))


@pytest.mark.parametrize("status", [401, 404])
def test_validation_rejects_invalid_credentials(status):
    with (
        patch(
            "api.infrastructure.telegram.client.get_config",
            return_value=MagicMock(skip_telegram_token_validation=False),
        ),
        patch("api.infrastructure.telegram.client.resilient_request", return_value=MagicMock(status_code=status)),
    ):
        ok, reason, identity = validate_bot_token("test-bot")
    assert_that(ok, equal_to(False))
    assert reason
    assert_that(identity, equal_to({}))


def test_validation_reports_unavailable_provider_without_identity():
    with (
        patch(
            "api.infrastructure.telegram.client.get_config",
            return_value=MagicMock(skip_telegram_token_validation=False),
        ),
        patch("api.infrastructure.telegram.client.resilient_request", side_effect=RuntimeError("unavailable")),
    ):
        assert_that(
            validate_bot_token("test-bot"), equal_to((False, "Could not reach Telegram to validate bot token", {}))
        )
