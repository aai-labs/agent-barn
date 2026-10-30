import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to

SCRIPT = Path(__file__).parents[2] / "domains/agents/scripts/agentbarn_artifacts.py"


@pytest.mark.parametrize(
    "first_state, first_failure", [("READY", None), ("UPLOADING", 409), ("UPLOADING", 404), ("UPLOADING", 503)]
)
def test_upload_reuses_ready_or_recovers_shared_staging(tmp_path, first_state, first_failure):
    calls = []
    local_file = tmp_path / "report.csv"
    local_file.write_bytes(b"content")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append("POST")
            state = first_state if calls.count("POST") == 1 else "READY"
            self.reply(201, {"id": "first" if state == "UPLOADING" else "final", "state": state})

        def do_PUT(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append("PUT")
            self.reply(first_failure, {"detail": "retry"})

        def do_GET(self):
            calls.append(self.path)
            self.reply(200, {"artifact": {"id": "final"}, "url": "https://example.test/file"})

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "upload", str(local_file)],
            env={
                **os.environ,
                "ARTIFACT_URL": f"http://127.0.0.1:{server.server_port}",
                "ARTIFACT_API_KEY": "test",
                "ARTIFACT_UPLOAD_ROOTS": str(tmp_path),
            },
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(json.loads(result.stdout)["artifact"]["id"], equal_to("final"))
    expected = ["POST"] if first_state == "READY" else ["POST", "PUT", "POST"]
    assert_that(calls, equal_to([*expected, "/artifacts/final/download-link"]))
