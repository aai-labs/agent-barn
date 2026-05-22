import json
import logging
import urllib.request
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"
_PAGE_SIZE = 200
_MAX_SEARCH_PAGES = 5


class SlackClient:
    def __init__(self, bot_token: str) -> None:
        self._token = bot_token

    def _get(self, method: str, params: dict) -> dict:
        url = f"{_BASE}/{method}?{urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self._token}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def get_channel_map(self) -> dict[str, str]:
        """Returns {channel_id: channel_name} for all accessible channels."""
        result: dict[str, str] = {}
        cursor = ""
        while True:
            params: dict = {
                "limit": 200,
                "exclude_archived": "true",
                "types": "public_channel,private_channel",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._get("conversations.list", params)
            except Exception as e:
                logger.warning("conversations.list request failed: %s", e)
                break
            if not data.get("ok"):
                logger.warning("conversations.list error: %s", data.get("error"))
                break
            for ch in data.get("channels", []):
                cid = ch.get("id", "")
                name = ch.get("name", "")
                if cid and name:
                    result[cid] = name
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return result

    def get_user_map(self) -> dict[str, str]:
        """Returns {user_id: display_name} for all workspace members."""
        result: dict[str, str] = {}
        cursor = ""
        while True:
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._get("users.list", params)
            except Exception as e:
                logger.warning("users.list request failed: %s", e)
                break
            if not data.get("ok"):
                logger.warning("users.list error: %s", data.get("error"))
                break
            for user in data.get("members", []):
                uid = user.get("id", "")
                if not uid:
                    continue
                profile = user.get("profile", {})
                name = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or user.get("name", uid)
                )
                result[uid] = name
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return result

    def search_channels(self, search: str | None = None, limit: int = 50) -> list[dict]:
        # When no search, return the first page only. With search, scan up to MAX_PAGES
        # so big workspaces don't time out — search may miss matches past the ceiling.
        max_pages = _MAX_SEARCH_PAGES if search else 1
        q = search.lower() if search else None
        matches: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params: dict = {
                "limit": _PAGE_SIZE,
                "exclude_archived": "true",
                "types": "public_channel,private_channel",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._get("conversations.list", params)
            except Exception as e:
                logger.warning("conversations.list request failed: %s", e)
                break
            if not data.get("ok"):
                logger.warning("conversations.list error: %s", data.get("error"))
                break
            for ch in data.get("channels", []):
                entry = {"id": ch.get("id", ""), "name": ch.get("name", "")}
                if (
                    q
                    and q not in entry["id"].lower()
                    and q not in entry["name"].lower()
                ):
                    continue
                matches.append(entry)
                if len(matches) >= limit:
                    return matches
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return matches

    def search_users(self, search: str | None = None, limit: int = 50) -> list[dict]:
        max_pages = _MAX_SEARCH_PAGES if search else 1
        q = search.lower() if search else None
        matches: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params: dict = {"limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._get("users.list", params)
            except Exception as e:
                logger.warning("users.list request failed: %s", e)
                break
            if not data.get("ok"):
                logger.warning("users.list error: %s", data.get("error"))
                break
            for u in data.get("members", []):
                if u.get("deleted") or u.get("is_bot"):
                    continue
                entry = {
                    "id": u.get("id", ""),
                    "name": u.get("name", ""),
                    "real_name": u.get("real_name", ""),
                }
                if q and not (
                    q in entry["id"].lower()
                    or q in entry["name"].lower()
                    or q in entry["real_name"].lower()
                ):
                    continue
                matches.append(entry)
                if len(matches) >= limit:
                    return matches
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return matches
