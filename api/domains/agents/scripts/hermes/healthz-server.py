import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PORT = 8081
PROXY_PORT = 8090
HERMES_URL = "http://localhost:8642/v1/models"
POLL_INTERVAL = 10
TOKEN_POLL_INTERVAL = 300  # 5 minutes

LITELLM_PROXY_TARGET = os.environ.get("LITELLM_PROXY_TARGET", "")

_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}
_token_cache: dict = {"ok": None, "reason": None}
_llm_cache: dict = {"ok": None, "reason": None}

AGENT_PLATFORM = os.environ.get("AGENT_PLATFORM", "slack")
_SLACK_API = "https://slack.com/api"
_TELEGRAM_API = "https://api.telegram.org"
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
        elif self.path == "/healthz":
            with _lock:
                ok = _cache["ok"]
                ever = _cache["ever_connected"]
                reason = _cache["reason"]
                tok_ok = _token_cache["ok"]
                tok_reason = _token_cache["reason"]
                llm_ok = _llm_cache["ok"]
                llm_reason = _llm_cache["reason"]

            # Token failures surface immediately as errors
            if tok_ok is False:
                self._send(500, {"status": "error", "reason": tok_reason})
                return

            if llm_ok is False:
                self._send(500, {"status": "error", "reason": llm_reason})
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
        assert _target_parsed is not None
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
                with _lock:
                    _llm_cache["ok"] = False
                    _llm_cache["reason"] = clean_msg
                self.send_response(upstream.status)
                for key, val in upstream.getheaders():
                    if key.lower() in ("content-type",):
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(clean_body)))
                self.end_headers()
                self.wfile.write(clean_body)
            else:
                with _lock:
                    if 200 <= upstream.status < 300:
                        _llm_cache["ok"] = True
                        _llm_cache["reason"] = None
                self.send_response(upstream.status)
                for key, val in upstream.getheaders():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.end_headers()
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

            conn.close()
        except Exception:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            err = json.dumps({"error": {"message": "LLM proxy upstream unreachable", "type": None, "param": None, "code": "502"}}).encode()
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)


if LITELLM_PROXY_TARGET:
    threading.Thread(
        target=lambda: ThreadingHTTPServer(("", PROXY_PORT), _ProxyHandler).serve_forever(),
        daemon=True,
    ).start()

HTTPServer(("", PORT), _Handler).serve_forever()
