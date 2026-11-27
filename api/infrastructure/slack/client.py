import hashlib
import json
from collections.abc import Iterator

from api.infrastructure.slack.cache import cached, clear_directory_cache
from api.infrastructure.slack.errors import (
    APP_TOKEN_ERRORS,
    BOT_TOKEN_ERRORS,
    SlackApiError,
    SlackFetchError,
)
from api.infrastructure.slack.transport import request_json

# Re-exported so callers can depend on the client module alone for the public
# surface, regardless of how the internals are split across modules.
__all__ = ["SlackApiError", "SlackClient", "SlackFetchError", "clear_directory_cache"]

SLACK_API_URL = "https://slack.com/api"
_PAGE_SIZE = 200


class SlackClient:
    """Talks to the Slack Web API for one workspace.

    The bot token authenticates directory and channel calls; the optional app
    token is only used by validate_app_token (apps.connections.open needs the
    app-level token, not the bot token). ``api_url`` points the client at a
    Slack-compatible server instead of Slack itself.
    """

    def __init__(self, bot_token: str, app_token: str | None = None, *, api_url: str | None = None) -> None:
        self._bot_token = bot_token
        self._app_token = app_token
        self._base = (api_url or SLACK_API_URL).rstrip("/")
        # A custom server is user-supplied and called from the API server.
        self._public_only = api_url is not None

    # --- transport helpers -------------------------------------------------

    def _get(self, method: str, params: dict) -> dict:
        return request_json(
            "GET",
            f"{self._base}/{method}",
            headers={"Authorization": f"Bearer {self._bot_token}"},
            params=params,
            public_only=self._public_only,
        )

    def _post(self, method: str, payload: dict) -> dict:
        return request_json(
            "POST",
            f"{self._base}/{method}",
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(payload).encode(),
            public_only=self._public_only,
        )

    def _iter_pages(self, method: str, params: dict, items_key: str) -> Iterator[list[dict]]:
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
        return self._validate(self._app_token, "apps.connections.open", APP_TOKEN_ERRORS, "app")

    def _validate(self, token: str | None, method: str, error_map: dict[str, str], label: str) -> tuple[bool, str]:
        if not token:
            return False, error_map["not_authed"]
        try:
            body = request_json(
                "POST",
                f"{self._base}/{method}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                content=b"",
                public_only=self._public_only,
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
                "user_id": body.get("user_id", ""),
                "bot_name": body.get("user", ""),
                "team": body.get("team", ""),
            }
        except Exception:
            return {}

    def get_workspace(self) -> dict:
        """The workspace this bot token belongs to: team_id, team (its name) and enterprise_id."""
        body = self._call("auth.test", {})
        if not body.get("team_id"):
            raise SlackFetchError("auth.test error: no_team_id")
        return {
            "team_id": body["team_id"],
            "team": body.get("team", ""),
            "enterprise_id": body.get("enterprise_id") or None,
        }

    def post_message(
        self, channel_id: str, text: str, thread_ts: str | None = None, blocks: list[dict] | None = None
    ) -> str:
        """Posts `text` (Slack mrkdwn) as the bot, in a thread when one is named; returns the message's ts.

        With `blocks`, Slack shows those and keeps `text` for notifications."""
        payload: dict = {"channel": channel_id, "text": text, "unfurl_links": False, "unfurl_media": False}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks
        body = self._call("chat.postMessage", payload)
        if not body.get("ts"):
            raise SlackFetchError("chat.postMessage error: no_ts")
        return str(body["ts"])

    def update_message(self, channel_id: str, ts: str, text: str, blocks: list[dict] | None = None) -> None:
        """Replaces the bot's own message at `ts`; an empty `blocks` list removes the earlier blocks."""
        payload: dict = {"channel": channel_id, "ts": ts, "text": text, "blocks": blocks or []}
        self._call("chat.update", payload)

    def _call(self, method: str, payload: dict) -> dict:
        try:
            body = self._post(method, payload)
        except Exception as exc:
            raise SlackFetchError(f"{method} request failed: {exc}") from exc
        if not body.get("ok"):
            raise SlackApiError(method, str(body.get("error") or "unknown_error"))
        return body

    def get_conversation(self, channel_id: str) -> dict:
        body = self._get("conversations.info", {"channel": channel_id})
        if not body.get("ok") or not body.get("channel"):
            raise SlackFetchError(f"conversations.info error: {body.get('error', 'unknown_error')}")
        return body["channel"]

    def open_dm(self, user_id: str) -> str:
        body = self._post("conversations.open", {"users": user_id})
        channel_id = (body.get("channel") or {}).get("id")
        if not body.get("ok"):
            raise SlackApiError("conversations.open", str(body.get("error") or "unknown_error"))
        if not channel_id:
            raise SlackFetchError("conversations.open error: no_channel")
        return str(channel_id)

    # --- cached directory listings -----------------------------------------

    def _token_key(self, kind: str) -> str:
        digest = hashlib.sha256(f"{self._base} {self._bot_token}".encode()).hexdigest()
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
        return [ch for ch in channels if q in ch["id"].lower() or q in ch["name"].lower()]

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

    # --- name resolution -----------------------------------------------
