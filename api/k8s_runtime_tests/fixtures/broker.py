"""In-cluster fake provider boundary. Never forwards requests to live providers."""

import http.server
import json
import threading
from typing import NotRequired, TypedDict


class Observations(TypedDict):
    handoffs: list[dict]
    tokens: int
    proxy_calls: int
    refuse_handoff: bool
    handback: NotRequired[dict]


observations: Observations = {"handoffs": [], "tokens": 0, "proxy_calls": 0, "refuse_handoff": True}


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/observations":
            self.reply(200, observations)
        elif self.path.startswith("/gateway/v1/p/github/"):
            if self.headers.get("Authorization") != "Bearer agt_github_fixture":
                self.reply(403, {"detail": "Fixture token rejected"})
                return
            observations["proxy_calls"] += 1
            self.reply(200, {"login": "fixture-user", "id": 1})
        else:
            self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/control":
            if "refuse_handoff" in body:
                observations["refuse_handoff"] = body["refuse_handoff"]
            else:
                observations["handback"] = body["handback"]
            self.reply(200, {})
            return
        if self.headers.get("Authorization") != "Bearer agt_sharepoint_fixture":
            self.reply(403, {"detail": "Fixture token rejected"})
            return
        if self.path == "/gateway/v1/sharepoint/handoff":
            observations["handoffs"].append(body)
            self.reply(409 if observations["refuse_handoff"] else 200, {})
        elif self.path == "/gateway/v1/token":
            observations["tokens"] += 1
            self.reply(
                200, {"access_token": "temporary-graph-access", "expires_in": 3600, "scopes": ["Sites.Read.All"]}
            )
        else:
            self.reply(404, {})

    def log_message(self, format, *args):
        pass


denied = http.server.HTTPServer(("0.0.0.0", 18081), Handler)
threading.Thread(target=denied.serve_forever, daemon=True).start()
http.server.HTTPServer(("0.0.0.0", 18080), Handler).serve_forever()
