import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

PORT = 8081
HERMES_URL = "http://localhost:8642/v1/models"
POLL_INTERVAL = 10

_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}


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
            if ok is None:
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


HTTPServer(("", PORT), _Handler).serve_forever()
