import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

PORT = int(os.environ.get("HEALTHZ_PORT", "8081"))
HERMES_URL = "http://localhost:8642/v1/models"
POLL_INTERVAL = 10
TOKEN_POLL_INTERVAL = 300  # 5 minutes

_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}
_token_cache: dict = {"ok": None, "reason": None}

AGENT_PLATFORM = os.environ.get("AGENT_PLATFORM", "slack")
_SLACK_API = "https://slack.com/api"
_TELEGRAM_API = "https://api.telegram.org"
_SKIP_VALIDATION = os.environ.get("SKIP_SLACK_TOKEN_VALIDATION", "").lower() in ("1", "true", "yes")


def _poll() -> None:
    api_key = os.environ.get("API_SERVER_KEY", "")
    while True:
        try:
            req = Request(HERMES_URL, headers={"Authorization": f"Bearer {api_key}"})
            with urlopen(req, timeout=15) as resp:
                resp.read()
            with _lock:
                _cache["ok"] = True
                _cache["ever_connected"] = True
                _cache["reason"] = None
        except (URLError, Exception) as exc:
            with _lock:
                _cache["ok"] = False
                _cache["reason"] = str(exc)
        time.sleep(POLL_INTERVAL)


def _check_token(url: str, token: str, label: str) -> tuple[bool, str]:
    try:
        req = Request(
            url,
            data=b"",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        if body.get("ok"):
            return True, ""
        return False, f"Invalid {label}: {body.get('error', 'unknown_error')}"
    except Exception as exc:
        return False, f"{label} validation failed: {exc}"


def _check_telegram_token(token: str) -> tuple[bool, str]:
    try:
        url = f"{_TELEGRAM_API}/bot{token}/getMe"
        req = Request(url)
        with urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        if body.get("ok"):
            return True, ""
        return False, f"Invalid Telegram bot token: {body.get('description', 'unknown_error')}"
    except Exception as exc:
        return False, f"Telegram token validation failed: {exc}"


def _poll_tokens() -> None:
    if _SKIP_VALIDATION:
        with _lock:
            _token_cache["ok"] = True
            _token_cache["reason"] = None
        return

    while True:
        if AGENT_PLATFORM == "telegram":
            telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            ok, reason = _check_telegram_token(telegram_token)
        else:
            bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
            app_token = os.environ.get("SLACK_APP_TOKEN", "")
            ok, reason = _check_token(f"{_SLACK_API}/auth.test", bot_token, "bot token")
            if ok:
                ok, reason = _check_token(f"{_SLACK_API}/apps.connections.open", app_token, "app token")
        with _lock:
            _token_cache["ok"] = ok
            _token_cache["reason"] = reason if not ok else None
        time.sleep(TOKEN_POLL_INTERVAL)


threading.Thread(target=_poll, daemon=True).start()
threading.Thread(target=_poll_tokens, daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/ready":
            self._send(200, {"ready": True})
        elif self.path == "/metrics":
            with _lock:
                ok = _cache["ok"]
                ever = _cache["ever_connected"]
                tok_ok = _token_cache["ok"]
            # Token gauge stays 1 while unknown/starting; 0 only on a definite
            # failure, so a slow first validation never trips an alert.
            lines = [
                "# HELP agent_healthz_ok 1 if the agent runtime is reachable, 0 otherwise",
                "# TYPE agent_healthz_ok gauge",
                f"agent_healthz_ok {1 if ok else 0}",
                "# HELP agent_healthz_ever_connected 1 once the runtime has connected at least once",
                "# TYPE agent_healthz_ever_connected gauge",
                f"agent_healthz_ever_connected {1 if ever else 0}",
                "# HELP agent_slack_tokens_ok 0 if Slack token validation definitely failed, 1 otherwise",
                "# TYPE agent_slack_tokens_ok gauge",
                f"agent_slack_tokens_ok {0 if tok_ok is False else 1}",
            ]
            self._send_text(200, "\n".join(lines) + "\n")
        elif self.path == "/healthz":
            with _lock:
                ok = _cache["ok"]
                ever = _cache["ever_connected"]
                reason = _cache["reason"]
                tok_ok = _token_cache["ok"]
                tok_reason = _token_cache["reason"]

            # Token failures surface immediately as errors
            if tok_ok is False:
                self._send(500, {"status": "error", "reason": tok_reason})
                return

            if ok is None or tok_ok is None:
                self._send(503, {"status": "starting"})
            elif ok:
                self._send(200, {"status": "ok"})
            elif ever:
                self._send(500, {"status": "error", "reason": reason})
            else:
                self._send(503, {"status": "starting", "reason": reason})
        else:
            self.send_response(404)
            self.end_headers()

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


HTTPServer(("", PORT), _Handler).serve_forever()
