import json
import urllib.parse

from fastapi import HTTPException, status

from api.infrastructure.slack.transport import request_json

_BASE = "https://slack.com/api"

_VALIDATION_MANIFEST: dict = {
    "display_information": {
        "name": "Agent Farm Validation",
        "description": "Temporary manifest validation",
    },
    "features": {
        "app_home": {
            "home_tab_enabled": False,
            "messages_tab_enabled": True,
            "messages_tab_read_only_enabled": False,
        },
        "bot_user": {
            "display_name": "Agent Farm Validation",
            "always_online": False,
        },
    },
    "oauth_config": {"scopes": {"bot": ["chat:write"]}},
    "settings": {
        "event_subscriptions": {"bot_events": ["message.im"]},
        "interactivity": {"is_enabled": True},
        "org_deploy_enabled": False,
        "socket_mode_enabled": True,
        "token_rotation_enabled": False,
    },
}


def _post_form(token: str, method: str, data: dict[str, str]) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    return request_json(
        "POST",
        f"{_BASE}/{method}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content=encoded,
    )


def validate_config_access_token(token: str) -> None:
    if token.startswith("xapp-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That looks like an app-level token (xapp-). Slack app creation "
                "requires a configuration access token."
            ),
        )
    if token.startswith("xoxb-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That looks like a bot token (xoxb-). Slack app creation "
                "requires a configuration access token."
            ),
        )
    if token.startswith("xoxp-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That looks like a user token (xoxp-). Slack app creation "
                "requires a configuration access token."
            ),
        )

    try:
        body = _post_form(
            token,
            "apps.manifest.validate",
            {"manifest": json.dumps(_VALIDATION_MANIFEST)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not reach Slack to validate configuration token: {exc}",
        ) from exc

    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slack configuration token validation failed: {error}",
        )


def rotate_refresh_token(refresh_token: str) -> tuple[str, str]:
    try:
        body = request_json(
            "POST",
            f"{_BASE}/tooling.tokens.rotate",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urllib.parse.urlencode(
                {"refresh_token": refresh_token},
            ).encode(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not reach Slack to rotate refresh token: {exc}",
        ) from exc

    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slack refresh token rotation failed: {error}",
        )

    access_token = body.get("token", "")
    new_refresh_token = body.get("refresh_token", "")
    if not access_token or not new_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slack refresh token rotation did not return a new token pair.",
        )

    validate_config_access_token(access_token)
    return access_token, new_refresh_token


def validate_config_credential(token: str) -> tuple[str, str | None]:
    if token.startswith("xoxe-") and not token.startswith("xoxe.xoxp-"):
        return rotate_refresh_token(token)

    validate_config_access_token(token)
    return token, None


def create_slack_app(access_token: str, manifest: dict) -> str:
    try:
        body = _post_form(
            access_token,
            "apps.manifest.create",
            {"manifest": json.dumps(manifest)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Slack to create app: {exc}",
        ) from exc

    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        if error == "invalid_auth":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Slack configuration token is invalid or expired. Please update "
                    "it in your account settings."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slack app creation failed: {error}",
        )

    app_id = body.get("app_id", "")
    if not app_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Slack returned success but no app_id.",
        )
    return app_id
