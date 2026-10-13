"""A loopback stand-in for the LiteLLM proxy's chat-completions endpoint."""

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# (status, body, headers) for one request.
StubReply = tuple[int, Any, dict[str, str]]


@dataclass
class StubProxy:
    status: int = 200
    body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    # When set, decides each reply from the posted JSON instead of the fixed fields above.
    respond: Callable[[dict[str, Any]], StubReply] | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


@contextmanager
def litellm_proxy(stub: StubProxy) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            posted = json.loads(self.rfile.read(length))
            with stub.lock:
                stub.requests.append(
                    {"path": self.path, "authorization": self.headers.get("Authorization"), "json": posted}
                )
            status, body, headers = stub.respond(posted) if stub.respond else (stub.status, stub.body, stub.headers)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def completion(content: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
