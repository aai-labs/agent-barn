"""Generated aai-cli Gmail profile run in a real image against a stub gateway, networking disabled."""

import json
import os
import shlex
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

artifacts = json.loads(Path("/contract/artifacts.json").read_text())
seen: list[dict] = []


class StubGateway(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"null")
        seen.append({"path": urlsplit(self.path).path, "auth": self.headers.get("Authorization"), "json": payload})
        target = payload["url"].rsplit("/", 1)[-1]
        body = {"messages": [{"id": "7"}]} if target == "messages" else {"id": target}
        reply = json.dumps({"status": 200, "body": body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format, *args):
        del format, args


server = HTTPServer(("127.0.0.1", 18080), StubGateway)
threading.Thread(target=server.serve_forever, daemon=True).start()

for name, value in artifacts["files"].items():
    Path(f"/app/config/{name}").write_text(value)
env = {**os.environ, **artifacts["env"], "HOME": artifacts["home"]}
setup = subprocess.run(["sh", "/app/config/aai-cli-setup.sh"], env=env, capture_output=True, text=True, check=False)
assert setup.returncode == 0, setup.stdout + setup.stderr


def aai_cli(command: str, run_env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(shlex.split(command), env=run_env, capture_output=True, text=True, timeout=15, check=False)


list_command, read_command = artifacts["commands"]
# The agent fills in the optional search and limit, and an id from the list.
list_command = list_command.split(" (", 1)[0] + " --query 'q=from:alice newer_than:7d' --query limit=5"
listed = aai_cli(list_command, env)
assert listed.returncode == 0, listed.stdout + listed.stderr
read = aai_cli(read_command.replace("<id>", "7"), env)
assert read.returncode == 0, read.stdout + read.stderr

before = len(seen)
token_env = next(key for key in artifacts["env"] if key.startswith("AF_GATEWAY_TOKEN_"))
without_token = aai_cli(list_command, {key: value for key, value in env.items() if key != token_env})
server.shutdown()

print(
    json.dumps(
        {
            "listed": json.loads(listed.stdout),
            "read": json.loads(read.stdout),
            "requests": seen[:before],
            "without_token_exit": without_token.returncode,
            "requests_without_token": len(seen) - before,
            "uid": os.getuid(),
        }
    )
)
