import hashlib
import json
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

from api.core.config import get_config

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"
_PAGE_SIZE = 200

_ALREADY_IN_CHANNEL = {"already_in_channel"}
_PRIVATE_CHANNEL_ERRORS = {"method_not_supported_for_channel_type", "is_private"}

# Process-local TTL cache for the workspace directory (users/channels), keyed by
# entity kind + hashed bot token. Slack has no user-search endpoint and users.list
# is rate-limited, so we sweep every page once per TTL and filter in memory.
# Fragmented per pod; swap for a shared store (Redis) keyed the same way if needed.
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def clear_directory_cache() -> None:
    """Drops all cached directory entries. Intended for tests."""
    with _cache_lock:
        _cache.clear()
        _key_locks.clear()


def _key_lock(key: str) -> threading.Lock:
    with _cache_lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def _cached(key: str, fetch: Callable[[], list[dict]]) -> list[dict]:
    """Returns cached entries for key, refreshing via fetch on miss/expiry.
    Per-key locking ensures a miss triggers exactly one Slack sweep.
    """
    ttl = get_config().slack_directory_cache_ttl_seconds
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    with _key_lock(key):
        # Re-check: another thread may have refreshed while we waited.
        now = time.monotonic()
        with _cache_lock:
            entry = _cache.get(key)
            if entry and now - entry[0] < ttl:
                return entry[1]
        data = fetch()
        with _cache_lock:
            _cache[key] = (time.monotonic(), data)
        return data


_BOT_TOKEN_ERRORS: dict[str, str] = {
    "invalid_auth": "Slack bot token is invalid. Check the token in your Slack app settings.",
    "token_revoked": "Slack bot token has been revoked. Generate a new one in your Slack app settings.",
    "account_inactive": "The Slack account linked to this bot token is inactive.",
    "not_authed": "No Slack bot token was provided.",
    "org_login_required": "This workspace requires enterprise authentication.",
    "ekm_access_denied": "Access denied by your organisation's key management settings.",
}

_APP_TOKEN_ERRORS: dict[str, str] = {
    "invalid_auth": "Slack app token is invalid. Check the token in your Slack app settings.",
    "token_revoked": "Slack app token has been revoked. Generate a new one in your Slack app settings.",
    "missing_scope": "Slack app token is missing the 'connections:write' scope. Add it in your Slack app configuration.",
    "not_authed": "No Slack app token was provided.",
    "org_login_required": "This workspace requires enterprise authentication.",
}


def validate_bot_token(token: str) -> tuple[bool, str]:
    """Validates a Slack bot token via auth.test. Returns (ok, error_message)."""
    try:
        req = urllib.request.Request(
            f"{_BASE}/auth.test",
            data=b"",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        if body.get("ok"):
            return True, ""
        code = body.get("error", "unknown_error")
        return False, _BOT_TOKEN_ERRORS.get(code, f"Slack bot token error: {code}")
    except Exception as exc:
        return False, f"Could not reach Slack to validate bot token: {exc}"


def validate_app_token(token: str) -> tuple[bool, str]:
    """Validates a Slack app-level token via apps.connections.open. Returns (ok, error_message)."""
    try:
        req = urllib.request.Request(
            f"{_BASE}/apps.connections.open",
            data=b"",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        if body.get("ok"):
            return True, ""
        code = body.get("error", "unknown_error")
        return False, _APP_TOKEN_ERRORS.get(code, f"Slack app token error: {code}")
    except Exception as exc:
        return False, f"Could not reach Slack to validate app token: {exc}"


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

    def _post(self, method: str, payload: dict) -> dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{_BASE}/{method}",
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

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

    def _token_key(self, kind: str) -> str:
        digest = hashlib.sha256(self._token.encode()).hexdigest()
        return f"{kind}:{digest}"

    def _fetch_all_channels(self) -> list[dict]:
        """Paginates conversations.list to the end. Returns every accessible channel."""
        result: list[dict] = []
        cursor = ""
        while True:
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
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return result

    def _fetch_all_users(self) -> list[dict]:
        """Paginates users.list to the end. Excludes deleted members and bots."""
        result: list[dict] = []
        cursor = ""
        while True:
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
                uid = u.get("id", "")
                if not uid or u.get("deleted") or u.get("is_bot"):
                    continue
                profile = u.get("profile", {})
                result.append(
                    {
                        "id": uid,
                        "name": u.get("name", ""),
                        "real_name": profile.get("real_name") or u.get("real_name", ""),
                        "display_name": profile.get("display_name", ""),
                    }
                )
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return result

    def list_channels(self, search: str | None = None) -> list[dict]:
        """Returns all channels (cached). Filters in memory when search is given."""
        channels = _cached(self._token_key("channels"), self._fetch_all_channels)
        if not search:
            return channels
        q = search.lower()
        return [
            ch for ch in channels if q in ch["id"].lower() or q in ch["name"].lower()
        ]

    def list_users(self, search: str | None = None) -> list[dict]:
        """Returns all workspace members (cached). Filters in memory when search is given."""
        users = _cached(self._token_key("users"), self._fetch_all_users)
        if not search:
            return users
        q = search.lower()
        return [
            u
            for u in users
            if q in u["id"].lower()
            or q in u["name"].lower()
            or q in u["real_name"].lower()
            or q in u["display_name"].lower()
        ]
