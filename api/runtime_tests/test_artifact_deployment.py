"""Opt-in real runtimes -> API -> persistent Garage -> authenticated Files UI."""

import base64
import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config as AlembicConfig
from hamcrest import assert_that, equal_to
from testcontainers.postgres import PostgresContainer

from api.core.config import Config
from api.domains.agents.builders.artifacts import ARTIFACT_COMMAND, ARTIFACT_TOOL
from api.domains.artifacts.service import ArtifactService
from api.runtime_tests.memory_helpers import selected_image
from api.scripts.provision_garage import ROOT
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.garage_deployment import persistent_garage
from api.tests.integration.test_artifacts import CONTENT, runtime_auth
from api.tests.integration.test_workflows import _GIVEN, auth, base


@contextmanager
def backend(client):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            pass

        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = client.request(self.command, self.path, headers=dict(self.headers), content=body)
            self.send_response(response.status_code)
            for key, value in response.headers.multi_items():
                if key.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_runtimes_persistent_garage_and_authenticated_files_ui(tmp_path):
    images = {runtime: selected_image(runtime) for runtime in ("hermes", "openclaw")}
    with (
        persistent_garage() as (storage, compose, restart),
        PostgresContainer("postgres:18", driver="psycopg2") as postgres,
    ):
        settings = {
            **storage,
            "DB_CONNECTION_URL": postgres.get_connection_url(),
            "SECRET_SIGNING_KEY": "artifact-deployment-fixture-key-32-chars",
            "PLATFORM_ADMIN_CREDENTIALS": "admin@example.com:StrongPass123",
            "ENVIRONMENT": "test",
            "ORGANIZATION_DEFAULT_LLM_BUDGET_USD": "100",
            "AGENT_DEFAULT_LLM_BUDGET_USD": "25",
            "ANALYTICS_ENABLED": "false",
            "CLOUDFLARE_API_TOKEN": "",
            "AGENTBARN_TELEGRAM_BOT_TOKEN": "",
        }
        with given([set_env_variable(settings)]):
            command.upgrade(AlembicConfig(str(ROOT / "api/alembic.ini")), "head")
            with given(_GIVEN) as context, backend(context.client) as api_url:
                headers = runtime_auth(context)
                for runtime, image in images.items():
                    workspace = "/workspace" if runtime == "hermes" else "/home/node/.openclaw/workspace"
                    with tempfile.TemporaryDirectory(prefix="artifact-deployment-cli-") as directory:
                        root = Path(directory)
                        root.chmod(0o777)
                        (root / "agentbarn_artifacts.py").write_text(ARTIFACT_TOOL)
                        (root / "agentbarn-artifacts").write_text(ARTIFACT_COMMAND)
                        (root / "agentbarn-artifacts").chmod(0o555)
                        filename = runtime + "-live.csv"
                        (root / filename).write_bytes(CONTENT)
                        result = subprocess.run(
                            [
                                "docker",
                                "run",
                                "--rm",
                                "--network",
                                "host",
                                "--entrypoint",
                                "/usr/local/bin/agentbarn-artifacts",
                                "-v",
                                f"{root}:/app/config:ro",
                                "-v",
                                f"{root}:{workspace}",
                                "-v",
                                f"{root / 'agentbarn-artifacts'}:/usr/local/bin/agentbarn-artifacts:ro",
                                "-e",
                                f"ARTIFACT_URL={api_url}/api/v1/agent-artifacts/runtime",
                                "-e",
                                "ARTIFACT_API_KEY=" + headers["Authorization"].removeprefix("Bearer "),
                                "-e",
                                f"ARTIFACT_UPLOAD_ROOTS={workspace}",
                                image,
                                "upload",
                                workspace + "/" + filename,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            check=False,
                        )
                        assert_that(result.returncode, equal_to(0), "Runtime file upload failed")
                        assert_that(json.loads(result.stdout)["artifact"]["filename"], equal_to(filename))
                subprocess.run([*compose, "down"], capture_output=True, check=True)
                assert_that(subprocess.run(restart, capture_output=True, check=False).returncode, equal_to(0))
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    ui_port = listener.getsockname()[1]
                context.injector.get(Config).web_app_url = f"http://127.0.0.1:{ui_port}"
                environment = {
                    **os.environ,
                    "NEXT_PUBLIC_BACKEND_URL": api_url,
                    "NEXT_DIST_DIR": ".next-e2e",
                    "ARTIFACT_LIVE_UI": f"http://127.0.0.1:{ui_port}",
                    "ARTIFACT_LIVE_ORG": str(context.organization.id),
                    "ARTIFACT_LIVE_AGENT": str(context.agent.id),
                    "ARTIFACT_LIVE_CONTENT": base64.b64encode(CONTENT).decode(),
                    "ARTIFACT_LIVE_SCREENSHOT": str(tmp_path / "files.png"),
                }
                with open(tmp_path / "next.log", "w") as log:
                    ui = subprocess.Popen(
                        ["pnpm", "exec", "next", "dev", "-p", str(ui_port)],
                        cwd=ROOT / "ui",
                        env=environment,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                    try:
                        for _ in range(90):
                            try:
                                if httpx.get(environment["ARTIFACT_LIVE_UI"] + "/login", timeout=2).status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(1)
                        probe = subprocess.run(
                            ["node", "tests/support/artifact-live-probe.mjs"],
                            cwd=ROOT / "ui",
                            env=environment,
                            capture_output=True,
                            text=True,
                            timeout=150,
                            check=False,
                        )
                        assert_that(probe.returncode, equal_to(0), probe.stderr)
                    finally:
                        os.killpg(ui.pid, signal.SIGTERM)
                        ui.wait(timeout=20)
                files = context.client.get(base(context) + "/artifacts", headers=auth(context)).json()["items"]
                assert_that(len(files), equal_to(2))
                for artifact in files:
                    context.client.delete(base(context) + f"/artifacts/{artifact['id']}", headers=auth(context))
                assert_that(context.injector.get(ArtifactService).purge(), equal_to(2))
