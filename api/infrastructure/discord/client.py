import hashlib
from typing import Any

from api.infrastructure.http import resilient_request
from api.infrastructure.shared.cache import cached

_BASE = "https://discord.com/api/v10"
_TIMEOUT_SECONDS = 15
_DIRECTORY_CACHE_TTL_SECONDS = 600
_USER_AGENT = "AgentBarn/1.0"
_MESSAGE_CHANNEL_TYPES = {0, 5, 10, 11, 12, 15}


class DiscordClient:
    """Discord API client for credential validation and credential-scoped directories."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._token_key = hashlib.sha256(bot_token.encode()).hexdigest()

    def _request(self, path: str, *, label: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = resilient_request(
                "GET",
                f"{_BASE}{path}",
                headers={"Authorization": f"Bot {self._bot_token}", "User-Agent": _USER_AGENT},
                params=params,
                timeout=_TIMEOUT_SECONDS,
                label=label,
                retry_server_errors=True,
            )
            if response.status_code in (401, 403, 404):
                return None
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _get(self, path: str, *, label: str) -> dict | None:
        body = self._request(path, label=label)
        return body if isinstance(body, dict) else None

    def _get_list(self, path: str, *, label: str, params: dict[str, str] | None = None) -> list[dict]:
        # Unlike _get, this must not swallow errors into an empty list: it backs the
        # guild/channel/member/role directory, which is cache.py-cached for 10 minutes
        # and has no other way to distinguish "genuinely empty" from "call failed"
        # (e.g. missing Server Members Intent) — a caller needs the raised error to
        # surface it to the UI instead of caching a false empty result.
        response = resilient_request(
            "GET",
            f"{_BASE}{path}",
            headers={"Authorization": f"Bot {self._bot_token}", "User-Agent": _USER_AGENT},
            params=params,
            timeout=_TIMEOUT_SECONDS,
            label=label,
            retry_server_errors=True,
        )
        response.raise_for_status()
        body = response.json()
        return [item for item in body if isinstance(item, dict)] if isinstance(body, list) else []

    def get_current_bot(self) -> dict[str, Any]:
        body = self._get("/users/@me", label="Discord get current bot")
        if not body or not body.get("id"):
            raise ValueError("Discord bot token is invalid")
        return body

    def get_current_application(self) -> dict[str, Any]:
        body = self._get("/oauth2/applications/@me", label="Discord get current application")
        if not body or not body.get("id"):
            raise ValueError("Discord application lookup failed")
        return body

    def list_guilds(self) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            return [
                {"id": str(guild["id"]), "name": str(guild.get("name") or guild["id"])}
                for guild in self._get_list("/users/@me/guilds", label="Discord list bot guilds")
                if guild.get("id")
            ]

        return cached(f"discord_guilds:{self._token_key}", fetch, ttl=_DIRECTORY_CACHE_TTL_SECONDS)

    def list_guild_channels(self, guild_id: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            return [
                {"id": str(channel["id"]), "name": str(channel.get("name") or channel["id"])}
                for channel in self._get_list(f"/guilds/{guild_id}/channels", label="Discord list guild channels")
                if channel.get("id") and channel.get("type") in _MESSAGE_CHANNEL_TYPES
            ]

        return cached(f"discord_guild_channels:{self._token_key}:{guild_id}", fetch, ttl=_DIRECTORY_CACHE_TTL_SECONDS)

    def list_guild_members(self, guild_id: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            members: list[dict[str, str]] = []
            after = ""
            while True:
                page = self._get_list(
                    f"/guilds/{guild_id}/members",
                    label="Discord list guild members",
                    params={"limit": "1000", **({"after": after} if after else {})},
                )
                for member in page:
                    user = member.get("user")
                    if not isinstance(user, dict) or not user.get("id") or user.get("bot"):
                        continue
                    user_id = str(user["id"])
                    members.append(
                        {
                            "id": user_id,
                            "name": str(
                                member.get("nick") or user.get("global_name") or user.get("username") or user_id
                            ),
                        }
                    )
                if len(page) < 1000:
                    break
                last = page[-1].get("user")
                after = str(last.get("id") or "") if isinstance(last, dict) else ""
                if not after:
                    break
            return members

        return cached(f"discord_guild_members:{self._token_key}:{guild_id}", fetch, ttl=_DIRECTORY_CACHE_TTL_SECONDS)

    def list_guild_roles(self, guild_id: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            return [
                {"id": str(role["id"]), "name": str(role.get("name") or role["id"])}
                for role in self._get_list(f"/guilds/{guild_id}/roles", label="Discord list guild roles")
                if role.get("id") and role.get("name") != "@everyone"
            ]

        return cached(f"discord_guild_roles:{self._token_key}:{guild_id}", fetch, ttl=_DIRECTORY_CACHE_TTL_SECONDS)
