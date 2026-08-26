import hashlib
import json
from typing import Any

from api.infrastructure.http import resilient_request
from api.infrastructure.shared.cache import cached

_BASE = "https://discord.com/api/v10"
_TIMEOUT_SECONDS = 15
_DIRECTORY_CACHE_TTL_SECONDS = 600


class DiscordClient:
    """Best-effort Discord directory lookups for activity display names."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._token_key = hashlib.sha256(bot_token.encode()).hexdigest()

    def _get(self, path: str, *, label: str) -> dict | None:
        try:
            response = resilient_request(
                "GET",
                f"{_BASE}{path}",
                headers={"Authorization": f"Bot {self._bot_token}"},
                timeout=_TIMEOUT_SECONDS,
                label=label,
                retry_server_errors=True,
            )
            if response.status_code in (401, 403, 404):
                return None
            response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else None
        except Exception:
            return None

    def get_current_bot(self) -> dict[str, Any]:
        body = self._get("/users/@me", label="Discord get current bot")
        if not body or not body.get("id"):
            raise ValueError("Discord bot token is invalid")
        return body

    def get_gateway_url(self) -> str:
        body = self._get("/gateway/bot", label="Discord get gateway")
        if not body or not body.get("url"):
            raise ValueError("Discord bot cannot open a Gateway session")
        return str(body["url"])

    def send_message(self, channel_id: str, text: str, *, reply_to_id: str | None = None) -> str:
        payload: dict[str, Any] = {
            "content": text,
            "allowed_mentions": {"parse": []},
        }
        if reply_to_id:
            payload["message_reference"] = {
                "message_id": reply_to_id,
                "channel_id": channel_id,
                "fail_if_not_exists": False,
            }
        response = resilient_request(
            "POST",
            f"{_BASE}/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {self._bot_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(payload).encode("utf-8"),
            timeout=_TIMEOUT_SECONDS,
            label="Discord create message",
            retry_server_errors=True,
        )
        response.raise_for_status()
        message_id = response.json().get("id")
        if not message_id:
            raise RuntimeError("Discord create message returned no message id")
        return str(message_id)

    def get_user_display_name(self, user_id: str) -> str | None:
        def fetch() -> str | None:
            body = self._get(f"/users/{user_id}", label="Discord get user")
            if not body:
                return None
            return body.get("global_name") or body.get("username")

        return cached(
            f"discord_user:{self._token_key}:{user_id}",
            fetch,
            ttl=_DIRECTORY_CACHE_TTL_SECONDS,
        )

    def get_channel_display_name(self, channel_id: str) -> str | None:
        def fetch() -> str | None:
            body = self._get(f"/channels/{channel_id}", label="Discord get channel")
            if not body:
                return None
            return body.get("name")

        return cached(
            f"discord_channel:{self._token_key}:{channel_id}",
            fetch,
            ttl=_DIRECTORY_CACHE_TTL_SECONDS,
        )
