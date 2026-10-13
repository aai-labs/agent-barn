from api.core.config import get_config
from api.infrastructure.http import resilient_request

_BASE = "https://api.telegram.org"
_TIMEOUT_SECONDS = 15


def _request_json(url: str, *, label: str = "Telegram") -> dict:
    resp = resilient_request(
        "GET",
        url,
        timeout=_TIMEOUT_SECONDS,
        label=label,
        retry_server_errors=True,
    )
    if resp.status_code == 401:
        return {"ok": False, "description": "Unauthorized — invalid bot token"}
    if resp.status_code == 404:
        return {"ok": False, "description": "Not Found — invalid bot token format"}
    resp.raise_for_status()
    return resp.json()


def validate_bot_token(bot_token: str) -> tuple[bool, str, dict]:
    """Validate a Telegram bot token via the getMe API.

    Returns (ok, error_reason, bot_info). On success bot_info contains
    {"id": int, "is_bot": bool, "username": str, "first_name": str}.
    """
    if get_config().skip_telegram_token_validation:
        return True, "", {"username": "skipped"}

    url = f"{_BASE}/bot{bot_token}/getMe"
    try:
        data = _request_json(url, label="Telegram getMe")
    except Exception:
        return False, "Could not reach Telegram to validate bot token", {}

    if data.get("ok"):
        return True, "", data.get("result", {})

    description = data.get("description", "unknown error")
    return False, f"Telegram bot token is invalid: {description}", {}
