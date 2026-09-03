import hashlib
import json
from typing import Any

from api.infrastructure.http import resilient_request
from api.infrastructure.shared.cache import cached

_BASE = "https://discord.com/api/v10"
_TIMEOUT_SECONDS = 15
_DIRECTORY_CACHE_TTL_SECONDS = 600
_MESSAGE_CHANNEL_TYPES = {0, 5, 10, 11, 12, 15}
_MAX_NONCE_LENGTH = 25


class DiscordClient:
    """Discord API client for Connection delivery and credential-scoped directories."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._token_key = hashlib.sha256(bot_token.encode()).hexdigest()

    def _request(self, path: str, *, label: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = resilient_request(
                "GET",
                f"{_BASE}{path}",
                headers={"Authorization": f"Bot {self._bot_token}"},
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
        body = self._request(path, label=label, params=params)
        return [item for item in body if isinstance(item, dict)] if isinstance(body, list) else []

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

    def send_message(
        self, channel_id: str, text: str, *, reply_to_id: str | None = None, idempotency_key: str | None = None
    ) -> str:
        payload: dict[str, Any] = {"content": text, "allowed_mentions": {"parse": []}}
        if idempotency_key:
            # Discord rejects a nonce longer than 25 characters with 400/50035, and the
            # provider key is a 64-character digest. The prefix stays deterministic per
            # Delivery, so retries still de-duplicate.
            payload["nonce"] = idempotency_key[:_MAX_NONCE_LENGTH]
            payload["enforce_nonce"] = True
        if reply_to_id:
            payload["message_reference"] = {
                "message_id": reply_to_id,
                "channel_id": channel_id,
                "fail_if_not_exists": False,
            }
        response = resilient_request(
            "POST",
            f"{_BASE}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {self._bot_token}", "Content-Type": "application/json"},
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

    def get_user_display_name(self, user_id: str) -> str | None:
        return cached(
            f"discord_user:{self._token_key}:{user_id}",
            lambda: self._display_name(self._get(f"/users/{user_id}", label="Discord get user")),
            ttl=_DIRECTORY_CACHE_TTL_SECONDS,
        )

    @staticmethod
    def _display_name(body: dict | None) -> str | None:
        return (body or {}).get("global_name") or (body or {}).get("username")

    def get_channel_display_name(self, channel_id: str) -> str | None:
        return cached(
            f"discord_channel:{self._token_key}:{channel_id}",
            lambda: (self._get(f"/channels/{channel_id}", label="Discord get channel") or {}).get("name"),
            ttl=_DIRECTORY_CACHE_TTL_SECONDS,
        )
