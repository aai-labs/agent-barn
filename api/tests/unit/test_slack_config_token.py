from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.infrastructure.slack.config_token import (
    create_slack_app,
    rotate_refresh_token,
    validate_config_access_token,
)

_TRANSPORT = "api.infrastructure.slack.config_token.request_json"


@pytest.mark.parametrize(
    ("token", "expected_fragment"),
    [
        ("xoxb-fake", "bot token"),
        ("xapp-fake", "app-level token"),
        ("xoxp-fake", "user token"),
    ],
)
def test_validate_config_access_token_rejects_wrong_types(
    token: str,
    expected_fragment: str,
):
    with pytest.raises(HTTPException) as exc:
        validate_config_access_token(token)

    assert exc.value.status_code == 400
    assert expected_fragment in exc.value.detail


@patch(_TRANSPORT, return_value={"ok": True})
def test_validate_config_access_token_success(mock_rj):
    validate_config_access_token("valid-config-token")

    mock_rj.assert_called_once()


@patch(_TRANSPORT, return_value={"ok": False, "error": "invalid_auth"})
def test_validate_config_access_token_failure(mock_rj):
    with pytest.raises(HTTPException) as exc:
        validate_config_access_token("bad-token")

    assert exc.value.status_code == 400
    assert "invalid_auth" in exc.value.detail


@patch(
    _TRANSPORT,
    return_value={
        "ok": True,
        "token": "xoxe.xoxp-new",
        "refresh_token": "xoxe-new",
    },
)
def test_rotate_refresh_token_success(mock_rj):
    with patch("api.infrastructure.slack.config_token.validate_config_access_token"):
        access, refresh = rotate_refresh_token("xoxe-old")

    assert access == "xoxe.xoxp-new"
    assert refresh == "xoxe-new"


@patch(_TRANSPORT, return_value={"ok": False, "error": "token_expired"})
def test_rotate_refresh_token_failure(mock_rj):
    with pytest.raises(HTTPException) as exc:
        rotate_refresh_token("xoxe-old")

    assert exc.value.status_code == 400
    assert "token_expired" in exc.value.detail


@patch(_TRANSPORT, return_value={"ok": True, "app_id": "A12345"})
def test_create_slack_app_success(mock_rj):
    app_id = create_slack_app(
        "access-token",
        {"display_information": {"name": "Test"}},
    )

    assert app_id == "A12345"


@patch(_TRANSPORT, return_value={"ok": False, "error": "invalid_auth"})
def test_create_slack_app_invalid_auth(mock_rj):
    with pytest.raises(HTTPException) as exc:
        create_slack_app("bad-token", {})

    assert exc.value.status_code == 400
    assert "invalid or expired" in exc.value.detail
