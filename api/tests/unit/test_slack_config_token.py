from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.infrastructure.slack.config_token import (
    create_slack_app,
    rotate_refresh_token,
    update_slack_app_name,
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


# --- update_slack_app_name --------------------------------------------------


def test_update_slack_app_name_success():
    _TRANSPORT_CT = "api.infrastructure.slack.config_token.request_json"
    export_resp = {
        "ok": True,
        "manifest": {
            "display_information": {"name": "Old Name"},
            "features": {"bot_user": {"display_name": "Old Name"}},
        },
    }
    update_resp = {"ok": True}
    with patch(_TRANSPORT_CT, side_effect=[export_resp, update_resp]) as mock_rj:
        result = update_slack_app_name("token", "AAPP123", "New Name")

    assert result is True
    # Second call (update) sends form-encoded body; decode then parse the manifest field.
    import json
    import urllib.parse

    update_call_args = mock_rj.call_args_list[1]
    form = urllib.parse.parse_qs(update_call_args[1]["content"].decode())
    sent_manifest = json.loads(form["manifest"][0])
    assert sent_manifest["display_information"]["name"] == "New Name"
    assert sent_manifest["features"]["bot_user"]["display_name"] == "New Name"


def test_update_slack_app_name_export_failure_returns_false():
    _TRANSPORT_CT = "api.infrastructure.slack.config_token.request_json"
    with patch(_TRANSPORT_CT, return_value={"ok": False, "error": "not_found"}):
        result = update_slack_app_name("token", "AAPP123", "New Name")

    assert result is False


def test_update_slack_app_name_network_error_returns_false():
    _TRANSPORT_CT = "api.infrastructure.slack.config_token.request_json"
    with patch(_TRANSPORT_CT, side_effect=Exception("connection refused")):
        result = update_slack_app_name("token", "AAPP123", "New Name")

    assert result is False
