import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROXY_PORT = 8090
PORT = int(os.environ.get("HEALTHZ_PORT", "8081"))
HERMES_URL = "http://localhost:8642/v1/models"
POLL_INTERVAL = 10
TOKEN_POLL_INTERVAL = 300  # 5 minutes

LITELLM_PROXY_TARGET = os.environ.get("LITELLM_PROXY_TARGET", "")

_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}
_token_cache: dict = {"ok": None, "reason": None}

AGENT_PLATFORM = os.environ.get("AGENT_PLATFORM", "slack")
_SLACK_API = "https://slack.com/api"
_TELEGRAM_API = "https://api.telegram.org"
_DISCORD_API = "https://discord.com/api/v10"
_SKIP_VALIDATION = os.environ.get("SKIP_SLACK_TOKEN_VALIDATION", "").lower() in ("1", "true", "yes")

_TERMINAL_LLM_ERRORS: dict[int, str] = {
    401: "LLM API key is invalid or expired. Check your API key configuration.",
    402: "OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits.",
    403: "LLM API access denied. Check your account permissions.",
}


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


def _check_discord_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "No Discord bot token was provided."
    try:
        req = Request(
            f"{_DISCORD_API}/users/@me",
            headers={"Authorization": f"Bot {token}"},
        )
        with urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        if body.get("id") and body.get("bot") is True:
            return True, ""
        return False, "Discord bot token validation returned an unexpected account."
    except HTTPError as exc:
        if exc.code in (401, 403):
            return False, "Discord bot token is invalid or unauthorized."
        return False, f"Discord token validation failed: HTTP {exc.code}"
    except Exception as exc:
        return False, f"Discord token validation failed: {exc}"


def _validate_platform_tokens() -> tuple[bool, str]:
    if AGENT_PLATFORM == "telegram":
        return _check_telegram_token(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    if AGENT_PLATFORM == "discord":
        return _check_discord_token(os.environ.get("DISCORD_BOT_TOKEN", ""))
    if AGENT_PLATFORM == "slack":
        ok, reason = _check_token(
            f"{_SLACK_API}/auth.test",
            os.environ.get("SLACK_BOT_TOKEN", ""),
            "bot token",
        )
        if ok:
            return _check_token(
                f"{_SLACK_API}/apps.connections.open",
                os.environ.get("SLACK_APP_TOKEN", ""),
                "app token",
            )
        return ok, reason
    return False, f"Unsupported agent platform: {AGENT_PLATFORM}"


def _poll_tokens() -> None:
    if _SKIP_VALIDATION:
        with _lock:
            _token_cache["ok"] = True
            _token_cache["reason"] = None
        return

    while True:
        ok, reason = _validate_platform_tokens()
        with _lock:
            _token_cache["ok"] = ok
            _token_cache["reason"] = reason if not ok else None
        time.sleep(TOKEN_POLL_INTERVAL)


threading.Thread(target=_poll, daemon=True).start()
threading.Thread(target=_poll_tokens, daemon=True).start()


def _snapshot() -> tuple:
    """One consistent read of both caches; handlers stay lock-free."""
    with _lock:
        return (
            _cache["ok"],
            _cache["ever_connected"],
            _cache["reason"],
            _token_cache["ok"],
            _token_cache["reason"],
        )


def _metrics_text(ok, ever, tok_ok) -> str:
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
    return "\n".join(lines) + "\n"


def _healthz_result(ok, ever, reason, tok_ok, tok_reason) -> tuple[int, dict]:
    # Token failures surface immediately as errors
    if tok_ok is False:
        return 500, {"status": "error", "reason": tok_reason}
    if ok is None or tok_ok is None:
        return 503, {"status": "starting"}
    if ok:
        return 200, {"status": "ok"}
    if ever:
        return 500, {"status": "error", "reason": reason}
    return 503, {"status": "starting", "reason": reason}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/ready":
            self._send(200, {"ready": True})
        elif self.path == "/metrics":
            ok, ever, _, tok_ok, _ = _snapshot()
            self._send_text(200, _metrics_text(ok, ever, tok_ok))
        elif self.path == "/healthz":
            code, body = _healthz_result(*_snapshot())
            self._send(code, body)
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
        # Prometheus exposition content type; canonical value lives in
        # api/core/metrics.py (standalone script, cannot import it).
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


# ---------------------------------------------------------------------------
# LLM proxy — intercepts terminal errors and returns clean messages
# ---------------------------------------------------------------------------

_target_parsed = urlparse(LITELLM_PROXY_TARGET) if LITELLM_PROXY_TARGET else None


class _ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def do_PATCH(self) -> None:
        self._forward()

    def _forward(self) -> None:
        if _target_parsed is None:
            self.send_error(500, "LLM proxy not configured")
            return

        conn = None
        headers_sent = False
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            use_ssl = _target_parsed.scheme == "https"
            host = _target_parsed.hostname or "localhost"
            port = _target_parsed.port or (443 if use_ssl else 80)

            if use_ssl:
                conn = http.client.HTTPSConnection(host, port, timeout=120)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=120)

            fwd_headers = {}
            for key in self.headers:
                if key.lower() not in ("host", "transfer-encoding"):
                    fwd_headers[key] = self.headers[key]

            conn.request(self.command, self.path, body=body, headers=fwd_headers)
            upstream = conn.getresponse()

            clean_msg = _TERMINAL_LLM_ERRORS.get(upstream.status)
            if clean_msg:
                upstream.read()
                clean_body = json.dumps(
                    {"error": {"message": clean_msg, "type": None, "param": None, "code": str(upstream.status)}}
                ).encode()
                self.send_response(upstream.status)
                for key, val in upstream.getheaders():
                    if key.lower() in ("content-type",):
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(clean_body)))
                self.end_headers()
                headers_sent = True
                self.wfile.write(clean_body)
            else:
                self.send_response(upstream.status)
                for key, val in upstream.getheaders():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.end_headers()
                headers_sent = True
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception:
            if not headers_sent:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                err = json.dumps(
                    {"error": {"message": "LLM proxy upstream unreachable", "type": None, "param": None, "code": "502"}}
                ).encode()
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
        finally:
            if conn:
                conn.close()


if LITELLM_PROXY_TARGET:
    threading.Thread(
        target=lambda: ThreadingHTTPServer(("", PROXY_PORT), _ProxyHandler).serve_forever(),
        daemon=True,
    ).start()

HTTPServer(("", PORT), _Handler).serve_forever()
