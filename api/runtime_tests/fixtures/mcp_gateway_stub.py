"""A stand-in for the credential gateway's MCP route, run in its own container.

It answers Streamable HTTP the way the real route does to a pod: a bearer token check,
405 for GET and HEAD, an `Mcp-Session-Id`, and SSE-framed answers. Every request is
appended to the log file as one JSON line.

Usage: python3 mcp_gateway_stub.py <port> <log> <token>
"""

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOG, TOKEN = int(sys.argv[1]), sys.argv[2], sys.argv[3]
TOOLS = [
    {"name": "search", "description": "Search the wiki.", "inputSchema": {"type": "object"}},
    {"name": "summarize", "description": "Summarize a page.", "inputSchema": {"type": "object"}},
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json", **headers) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, message: dict) -> None:
        with open(LOG, "a") as handle:
            entry = {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "session": self.headers.get("Mcp-Session-Id"),
                "rpc": message.get("method"),
            }
            handle.write(json.dumps(entry) + "\n")

    def _route(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) if self.command == "POST" else b""
        message = json.loads(raw) if raw else {}
        self._record(message)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(403, b'{"error":"Invalid MCP gateway credential"}')
        if self.command in ("GET", "HEAD"):
            return self._send(405, Allow="POST, DELETE")
        if self.command == "DELETE":
            return self._send(200)
        rid = message.get("id")
        if message.get("method") == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stub", "version": "1.0"},
            }
            body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
            return self._send(200, body, **{"Mcp-Session-Id": uuid.uuid4().hex})
        if rid is None:
            return self._send(202)
        if message.get("method") == "tools/list":
            event = json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
            return self._send(200, f"event: message\ndata: {event}\n\n".encode(), "text/event-stream")
        return self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}).encode())

    do_GET = do_HEAD = do_POST = do_DELETE = _route


ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
