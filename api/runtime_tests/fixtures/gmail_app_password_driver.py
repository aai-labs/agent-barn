"""Generated Gmail helper run in a real image against a stub gateway, networking disabled."""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

artifacts = json.loads(Path("/contract/artifacts.json").read_text())
seen: list[dict] = []


class StubGateway(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        seen.append({"path": url.path, "query": parse_qs(url.query), "auth": self.headers.get("Authorization")})
        body = {"messages": [{"id": "7"}]} if url.path.endswith("/messages") else {"id": url.path.rsplit("/", 1)[-1]}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        del format, args


server = HTTPServer(("127.0.0.1", 18080), StubGateway)
threading.Thread(target=server.serve_forever, daemon=True).start()

for name, value in artifacts["files"].items():
    Path(f"/app/config/{name}").write_text(value)
env = {**os.environ, **artifacts["env"], "HOME": artifacts["home"]}


def helper(*args):
    return subprocess.run(
        ["sh", "/app/config/gmail-read.sh", *args], env=env, capture_output=True, text=True, timeout=15, check=False
    )


listed = helper("list", "from:alice", "newer_than:7d")
assert listed.returncode == 0, listed.stdout + listed.stderr
read = helper("get", "7")
assert read.returncode == 0, read.stdout + read.stderr
refused = helper("send", "7")
server.shutdown()

print(
    json.dumps(
        {
            "listed": json.loads(listed.stdout),
            "read": json.loads(read.stdout),
            "refused_exit": refused.returncode,
            "requests": seen,
            "uid": os.getuid(),
        }
    )
)
