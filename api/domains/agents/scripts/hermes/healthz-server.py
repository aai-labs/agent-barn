import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROXY_PORT = int(os.environ.get("LLM_PROXY_PORT", "8090"))
PORT = int(os.environ.get("HEALTHZ_PORT", "8081"))
# Test-only override; the builders never set it.
CGROUP_ROOT = os.environ.get("HEALTHZ_CGROUP_ROOT", "/sys/fs/cgroup")
HERMES_URL = "http://127.0.0.1:8642/v1/models"
POLL_INTERVAL = 10

LITELLM_PROXY_TARGET = os.environ.get("LITELLM_PROXY_TARGET", "")
_lock = threading.Lock()
_cache: dict = {"ok": None, "ever_connected": False, "reason": None}

_TERMINAL_LLM_ERRORS: dict[int, str] = {
    401: "LLM API key is invalid or expired. Check your API key configuration.",
    402: "OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits.",
    403: "LLM API access denied. Check your account permissions.",
}

# Neutral about whose limit ran out: the Agent's own and its Organization's come back
# as the same error type, and telling them apart would mean parsing upstream text.
_BUDGET_EXHAUSTED = (
    "A model spend limit has been reached, so this agent cannot reply right now. "
    "Contact your administrator to raise it or wait for the limit to renew."
)


# An exhausted limit has been seen as a 400, is documented as a 429, and is a 422 by
# default on LiteLLM releases after the pinned one, depending on which budget was hit
# and which proxy version answered. All are buffered and matched on the error body, so
# a version difference cannot leak the upstream text.
_BUDGET_STATUSES = (400, 422, 429)
# Terminal for both runtimes, like the credits-exhausted 402 above.
_BUDGET_EXHAUSTED_STATUS = 402

# Where the Communications adapter in this container learns why a turn failed. The
# runtime does not carry the reason out reliably (it can replace this proxy's
# message with its own), so the refusal is recorded here and read there.
_LLM_ERROR_MARKER = os.environ.get("AGENTBARN_LLM_ERROR_MARKER", "/tmp/agentbarn-llm-terminal-error.json")


def _record_terminal_llm_error(code: str) -> None:
    """Best effort: a failed write costs the person chatting a precise reason, never
    the response itself."""
    try:
        tmp = f"{_LLM_ERROR_MARKER}.tmp"
        with open(tmp, "w") as handle:
            json.dump({"code": code, "at": time.time()}, handle)
        os.replace(tmp, _LLM_ERROR_MARKER)
    except OSError:
        pass


def _budget_message(body: bytes) -> str | None:
    """Matched on the body rather than the status: these statuses also carry malformed
    requests, unknown models and rate limits, which must keep their own errors. The
    upstream text names an internal team id, so it is replaced, never passed through.
    """
    try:
        error = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        return None
    if not isinstance(error, dict) or error.get("type") != "budget_exceeded":
        return None
    return _BUDGET_EXHAUSTED


def _spend_limit_completion(path: str, request_body: bytes | None) -> tuple[str, bytes] | None:
    """An ordinary assistant reply carrying the spend-limit notice, in the request's format.

    Native chat posts whatever the runtime answers, so a refused chat completion answered
    as an error reaches the channel as the runtime's own billing text, or not at all. The
    marker still lets the Web Chat adapter report the turn as SPEND_LIMIT_REACHED.
    Requests that are not chat completions, or that cannot be read back, keep the 402.
    """
    if not path.split("?", 1)[0].endswith("/chat/completions") or not request_body:
        return None
    try:
        request = json.loads(request_body)
    except ValueError:
        return None
    if not isinstance(request, dict):
        return None
    completion_id = f"chatcmpl-agentbarn-spend-limit-{int(time.time() * 1000)}"
    created = int(time.time())
    model = request.get("model") if isinstance(request.get("model"), str) else "agentbarn-spend-limit"
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if request.get("stream") is True:
        base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model}
        chunks = [
            {
                **base,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": _BUDGET_EXHAUSTED}, "finish_reason": None}
                ],
            },
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage},
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return "text/event-stream; charset=utf-8", body.encode()
    body = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": _BUDGET_EXHAUSTED}, "finish_reason": "stop"}
        ],
        "usage": usage,
    }
    return "application/json", json.dumps(body).encode()


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


def _parse_uint(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isascii() and text.isdigit() else None


def _cgroup_text(name: str) -> str | None:
    try:
        with open(os.path.join(CGROUP_ROOT, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _cgroup_int(name: str) -> int | None:
    """A single-number cgroup file; `max` (no limit) and unreadable both give None."""
    text = _cgroup_text(name)
    return None if text is None else _parse_uint(text)


def _cgroup_keyed(name: str) -> dict[str, int]:
    """A flat `key value` cgroup file. Unknown and malformed lines are skipped."""
    values: dict[str, int] = {}
    for line in (_cgroup_text(name) or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and (value := _parse_uint(parts[1])) is not None:
            values[parts[0]] = value
    return values


def _cpu_limit_cores() -> float | None:
    parts = (_cgroup_text("cpu.max") or "").split()
    if len(parts) != 2:
        return None
    quota, period = _parse_uint(parts[0]), _parse_uint(parts[1])
    return quota / period if quota and period else None


def _resource_metrics_text() -> str:
    """Container CPU and memory from the cgroup v2 files. Every series is
    independent: one that cannot be read is left out, never guessed. The order and
    help text must match openclaw/healthz-server.js (a test compares them)."""
    current = _cgroup_int("memory.current")
    inactive = _cgroup_keyed("memory.stat").get("inactive_file")
    cpu_stat = _cgroup_keyed("cpu.stat")
    usage_usec = cpu_stat.get("usage_usec")
    working_set = max(current - inactive, 0) if current is not None and inactive is not None else None
    series = [
        (
            "agent_cgroup_metrics_available",
            "gauge",
            "1 if the container's cgroup v2 CPU and memory files were readable at this scrape, 0 otherwise",
            1 if working_set is not None and usage_usec is not None else 0,
        ),
        (
            "agent_memory_working_set_bytes",
            "gauge",
            "Container memory in use excluding reclaimable page cache (memory.current minus inactive_file)",
            working_set,
        ),
        (
            "agent_memory_limit_bytes",
            "gauge",
            "Container memory limit (memory.max); absent when unlimited",
            _cgroup_int("memory.max"),
        ),
        (
            "agent_cpu_usage_seconds_total",
            "counter",
            "CPU time consumed by the container (cpu.stat usage_usec)",
            None if usage_usec is None else usage_usec / 1e6,
        ),
        (
            "agent_cpu_limit_cores",
            "gauge",
            "Container CPU limit in cores (cpu.max quota / period); absent when unlimited",
            _cpu_limit_cores(),
        ),
        (
            "agent_cpu_periods_total",
            "counter",
            "CFS enforcement periods elapsed (cpu.stat nr_periods)",
            cpu_stat.get("nr_periods"),
        ),
        (
            "agent_cpu_throttled_periods_total",
            "counter",
            "CFS periods in which the container was throttled (cpu.stat nr_throttled)",
            cpu_stat.get("nr_throttled"),
        ),
    ]
    lines: list[str] = []
    for name, kind, help_text, value in series:
        if value is not None:
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", f"{name} {value}"]
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
    """Report sidecar liveness independently of native provider-session health."""
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
            self._send_text(200, _metrics_text(ok, ever) + _resource_metrics_text())
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
            status = upstream.status
            buffered: bytes | None = None
            if clean_msg is None and upstream.status in _BUDGET_STATUSES:
                # Only these are buffered. Everything else is either already mapped or
                # must keep streaming, which reading it here would break.
                buffered = upstream.read()
                clean_msg = _budget_message(buffered)
                if clean_msg:
                    # A spent limit is answered as 402 whatever the proxy said: it
                    # usually says 429, which the runtime retries as a rate limit
                    # indefinitely, so the person chatting would never hear back.
                    status = _BUDGET_EXHAUSTED_STATUS
                    _record_terminal_llm_error("SPEND_LIMIT_REACHED")
                    completion = _spend_limit_completion(self.path, body)
                    if completion is not None:
                        content_type, completion_body = completion
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(completion_body)))
                        self.end_headers()
                        headers_sent = True
                        self.wfile.write(completion_body)
                        return

            if clean_msg:
                if buffered is None:
                    upstream.read()
                clean_body = json.dumps(
                    {"error": {"message": clean_msg, "type": None, "param": None, "code": str(status)}}
                ).encode()
                self.send_response(status)
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
                if buffered is not None:
                    # Already consumed while checking for a budget rejection.
                    self.wfile.write(buffered)
                else:
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
