import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROXY_PORT = 8090
PORT = int(os.environ.get("HEALTHZ_PORT", "8081"))
HERMES_URL = "http://localhost:8642/v1/models"
POLL_INTERVAL = 10

LITELLM_PROXY_TARGET = os.environ.get("LITELLM_PROXY_TARGET", "")
_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}

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


threading.Thread(target=_poll, daemon=True).start()


def _snapshot() -> tuple:
    """One consistent read of the runtime cache; handlers stay lock-free."""
    with _lock:
        return (
            _cache["ok"],
            _cache["ever_connected"],
            _cache["reason"],
        )


def _metrics_text(ok, ever) -> str:
    lines = [
        "# HELP agent_healthz_ok 1 if the agent runtime is reachable, 0 otherwise",
        "# TYPE agent_healthz_ok gauge",
        f"agent_healthz_ok {1 if ok else 0}",
        "# HELP agent_healthz_ever_connected 1 once the runtime has connected at least once",
        "# TYPE agent_healthz_ever_connected gauge",
        f"agent_healthz_ever_connected {1 if ever else 0}",
    ]
    return "\n".join(lines) + "\n"


def _healthz_result(ok, ever, reason) -> tuple[int, dict]:
    if ok is None:
        return 503, {"status": "starting"}
    if ok:
        return 200, {"status": "ok"}
    if ever:
        return 500, {"status": "error", "reason": reason}
    return 503, {"status": "starting", "reason": reason}


def _liveness_result() -> tuple[int, dict]:
    """The sidecar process is live; provider sessions run in Communications."""
    return 200, {"live": True}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/ready":
            self._send(200, {"ready": True})
        elif self.path == "/live":
            self._send(*_liveness_result())
        elif self.path == "/metrics":
            ok, ever, _ = _snapshot()
            self._send_text(200, _metrics_text(ok, ever))
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
