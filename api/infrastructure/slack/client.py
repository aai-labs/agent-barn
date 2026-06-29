import hashlib
import json
import logging
from collections.abc import Iterator

from api.infrastructure.slack.cache import cached, clear_directory_cache
from api.infrastructure.slack.errors import (
    APP_TOKEN_ERRORS,
    BOT_TOKEN_ERRORS,
    SlackFetchError,
)
from api.infrastructure.slack.transport import request_json

logger = logging.getLogger(__name__)

# Re-exported so callers can depend on the client module alone for the public
# surface, regardless of how the internals are split across modules.
__all__ = ["SlackClient", "SlackFetchError", "clear_directory_cache"]

_BASE = "https://slack.com/api"
_PAGE_SIZE = 200

_ALREADY_IN_CHANNEL = {"already_in_channel"}
_PRIVATE_CHANNEL_ERRORS = {"method_not_supported_for_channel_type", "is_private"}


class SlackClient:
    """Talks to the Slack Web API for one workspace.

    The bot token authenticates directory and channel calls; the optional app
    token is only used by validate_app_token (apps.connections.open needs the
    app-level token, not the bot token).
    """

    def __init__(self, bot_token: str, app_token: str | None = None) -> None:
        self._bot_token = bot_token
        self._app_token = app_token

    # --- transport helpers -------------------------------------------------

    def _get(self, method: str, params: dict) -> dict:
        return request_json(
            "GET",
            f"{_BASE}/{method}",
            headers={"Authorization": f"Bearer {self._bot_token}"},
            params=params,
        )

    def _post(self, method: str, payload: dict) -> dict:
        return request_json(
            "POST",
            f"{_BASE}/{method}",
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(payload).encode(),
        )

    def _iter_pages(
        self, method: str, params: dict, items_key: str
    ) -> Iterator[list[dict]]:
        """Yields each page's items_key list, walking the cursor to the end.

        Raises SlackFetchError on a request failure or a non-ok Slack response so
        no caller mistakes a partial sweep for the complete result.
        """
        cursor = ""
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            try:
                data = self._get(method, page_params)
            except Exception as exc:
                raise SlackFetchError(f"{method} request failed: {exc}") from exc
            if not data.get("ok"):
                raise SlackFetchError(f"{method} error: {data.get('error')}")
            yield data.get(items_key, [])
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

    # --- token validation --------------------------------------------------

    def validate_bot_token(self) -> tuple[bool, str]:
        """Validates the bot token via auth.test. Returns (ok, error_message)."""
        return self._validate(self._bot_token, "auth.test", BOT_TOKEN_ERRORS, "bot")

    def validate_app_token(self) -> tuple[bool, str]:
        """Validates the app-level token via apps.connections.open. Returns (ok, error_message)."""
        return self._validate(
            self._app_token, "apps.connections.open", APP_TOKEN_ERRORS, "app"
        )

    @staticmethod
    def _validate(
        token: str | None, method: str, error_map: dict[str, str], label: str
    ) -> tuple[bool, str]:
        if not token:
            return False, error_map["not_authed"]
        try:
            body = request_json(
                "POST",
                f"{_BASE}/{method}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                content=b"",
            )
        except Exception as exc:
            return False, f"Could not reach Slack to validate {label} token: {exc}"
        if body.get("ok"):
            return True, ""
        code = body.get("error", "unknown_error")
        return False, error_map.get(code, f"Slack {label} token error: {code}")

    def get_bot_info(self) -> dict:
        """Returns app_id, bot username, and team from auth.test. Empty dict on failure."""
        try:
            body = self._post("auth.test", {})
            if not body.get("ok"):
                return {}
            return {
                "app_id": body.get("app_id", ""),
                "bot_name": body.get("user", ""),
                "team": body.get("team", ""),
            }
        except Exception:
            return {}

    # --- channel actions ---------------------------------------------------

    def join_channel(self, channel_id: str) -> bool:
        """Best-effort join for public channels. Returns True if joined or already a member.
        Returns False for private channels (requires manual invite). Never raises.
        """
        try:
            body = self._post("conversations.join", {"channel": channel_id.strip()})
        except Exception as e:
            logger.warning(
                "conversations.join request failed for %s: %s", channel_id, e
            )
            return False

        if body.get("ok"):
            return True
        error = str(body.get("error") or "unknown_error")
        if error in _ALREADY_IN_CHANNEL:
            return True
        if error in _PRIVATE_CHANNEL_ERRORS:
            logger.info("Cannot auto-join private channel %s: %s", channel_id, error)
            return False
        logger.warning("conversations.join failed for %s: %s", channel_id, error)
        return False

    # --- cached directory listings -----------------------------------------

    def _token_key(self, kind: str) -> str:
        digest = hashlib.sha256(self._bot_token.encode()).hexdigest()
        return f"{kind}:{digest}"

    def _fetch_all_channels(self) -> list[dict]:
        """Paginates conversations.list to the end. Returns every accessible channel."""
        result: list[dict] = []
        for channels in self._iter_pages(
            "conversations.list",
            {
                "limit": _PAGE_SIZE,
                "exclude_archived": "true",
                "types": "public_channel,private_channel",
            },
            "channels",
        ):
            for ch in channels:
                cid = ch.get("id", "")
                if not cid:
                    continue
                result.append(
                    {
                        "id": cid,
                        "name": ch.get("name", ""),
                        "is_private": ch.get("is_private", False),
                    }
                )
        return result

    def _fetch_all_users(self) -> list[dict]:
        """Paginates users.list to the end. Returns the full membership.

        Bots and deleted members are kept (with is_bot/deleted flags) so a single
        cached sweep serves both the directory picker, which filters them out, and
        name resolution, which needs them — list_users applies the filter at read.
        """
        result: list[dict] = []
        for members in self._iter_pages("users.list", {"limit": _PAGE_SIZE}, "members"):
            for u in members:
                uid = u.get("id", "")
                if not uid:
                    continue
                profile = u.get("profile", {})
                result.append(
                    {
                        "id": uid,
                        "name": u.get("name", ""),
                        "real_name": profile.get("real_name") or u.get("real_name", ""),
                        "display_name": profile.get("display_name", ""),
                        "is_bot": bool(u.get("is_bot")),
                        "deleted": bool(u.get("deleted")),
                    }
                )
        return result

    def list_channels(self, search: str | None = None) -> list[dict]:
        """Returns all channels (cached). Filters in memory when search is given."""
        channels = cached(self._token_key("channels"), self._fetch_all_channels)
        if not search:
            return channels
        q = search.lower()
        return [
            ch for ch in channels if q in ch["id"].lower() or q in ch["name"].lower()
        ]

    def list_users(
        self,
        search: str | None = None,
        *,
        include_bots: bool = False,
        include_deleted: bool = False,
    ) -> list[dict]:
        """Returns workspace members (cached), projected to {id, name, real_name, display_name}.

        Bots and deleted members are excluded by default (the directory picker wants
        real, active people); pass the include_* flags to keep them. Filtering and
        search run in memory over a single cached full-membership sweep.
        """
        users = cached(self._token_key("users"), self._fetch_all_users)
        q = search.lower() if search else None
        result: list[dict] = []
        for u in users:
            if not include_bots and u["is_bot"]:
                continue
            if not include_deleted and u["deleted"]:
                continue
            if q is not None and not (
                q in u["id"].lower()
                or q in u["name"].lower()
                or q in u["real_name"].lower()
                or q in u["display_name"].lower()
            ):
                continue
            result.append(
                {
                    "id": u["id"],
                    "name": u["name"],
                    "real_name": u["real_name"],
                    "display_name": u["display_name"],
                }
            )
        return result
