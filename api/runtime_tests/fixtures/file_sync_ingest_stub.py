import hashlib
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/contract-out/requests.jsonl"
READY = "/tmp/file-sync-stub-ready"
PORT = 18081
CHANGES = re.compile(r"^/ingest/v1/agents/[^/]+/file-sync/changes$")
COMPLETE = re.compile(r"^/ingest/v1/agents/[^/]+/file-sync/uploads/complete$")
OPERATIONS = re.compile(r"^/ingest/v1/agents/[^/]+/file-sync/operations$")
UPLOADS = {}


def record(entry):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return None

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _send(self, status, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return self.headers.get("Authorization") == "Bearer " + os.environ["INGEST_API_KEY"]

    def do_POST(self):
        body = self._body()
        if CHANGES.match(self.path) or COMPLETE.match(self.path):
            record({"method": "POST", "path": self.path, "body": json.loads(body)})
        if not self._authorized():
            self._send(401)
        elif CHANGES.match(self.path):
            uploads = []
            for entry in json.loads(body)["entries"]:
                if entry["size"] == 0:
                    continue
                token = str(len(UPLOADS) + 1)
                UPLOADS[token] = entry["path"]
                uploads.append(
                    {
                        "path": entry["path"],
                        "url": f"http://127.0.0.1:{PORT}/upload/{token}",
                        "expires_at": "2099-01-01T00:00:00Z",
                    }
                )
            self._send(200, {"uploads": uploads})
        elif COMPLETE.match(self.path):
            self._send(204)
        else:
            self._send(404)

    def do_GET(self):
        if OPERATIONS.match(self.path) and self._authorized():
            record({"method": "GET", "path": self.path})
            self._send(200, {"operations": []})
        else:
            self._send(404)

    def do_PUT(self):
        body = self._body()
        token = self.path.rsplit("/", 1)[-1]
        record(
            {
                "method": "PUT",
                "path": UPLOADS.get(token),
                "range": self.headers.get("Content-Range"),
                "authorization": self.headers.get("Authorization"),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        self._send(201, {"id": token})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    with open(READY, "w", encoding="utf-8"):
        pass
    server.serve_forever()


if __name__ == "__main__":
    main()
