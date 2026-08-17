import hashlib

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
