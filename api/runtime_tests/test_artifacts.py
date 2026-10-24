"""Generated artifact CLI in each real image, against the API, PostgreSQL and Garage.

No model or messaging provider is simulated as evidence of live execution.
"""

import json
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from hamcrest import assert_that, equal_to, has_length
from testcontainers.postgres import PostgresContainer

from api.domains.agents.builders.artifacts import ARTIFACT_COMMAND, ARTIFACT_TOOL
from api.runtime_tests.memory_helpers import selected_image
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.artifacts import garage_storage
from api.tests.integration.test_artifacts import CONTENT, runtime_auth
from api.tests.integration.test_workflows import _GIVEN


@contextmanager
def product_listener(client):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            pass

        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = client.request(self.command, self.path, headers=dict(self.headers), content=body)
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_PUT = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/artifact-runtime/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_real_image_cli_publishes_lists_links_and_retrieves(runtime):
    image = selected_image(runtime)
    with PostgresContainer("postgres:18", driver="psycopg2") as postgres, garage_storage() as (storage, _):
        settings = {
            **storage,
            "DB_CONNECTION_URL": postgres.get_connection_url(),
            "SECRET_SIGNING_KEY": "artifact-runtime-fixture-signing-key",
            "PLATFORM_ADMIN_CREDENTIALS": "admin@example.com:StrongPass123",
            "ORGANIZATION_DEFAULT_LLM_BUDGET_USD": "100",
            "AGENT_DEFAULT_LLM_BUDGET_USD": "25",
            "ANALYTICS_ENABLED": "false",
            "CLOUDFLARE_API_TOKEN": "",
            "AGENTBARN_TELEGRAM_BOT_TOKEN": "",
        }
        with given([set_env_variable(settings)]) as _:
            command.upgrade(AlembicConfig(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
            with given(_GIVEN) as context, tempfile.TemporaryDirectory(prefix="artifact-runtime-") as directory:
                headers = runtime_auth(context)
                root = Path(directory)
                root.chmod(0o777)
                (root / "agentbarn_artifacts.py").write_text(ARTIFACT_TOOL)
                (root / "agentbarn-artifacts").write_text(ARTIFACT_COMMAND)
                (root / "agentbarn-artifacts").chmod(0o555)
                (root / "report.csv").write_bytes(CONTENT)
                workspace = "/workspace" if runtime == "hermes" else "/home/node/.openclaw/workspace"
                with product_listener(context.client) as url:

                    def cli(*arguments):
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
                                f"ARTIFACT_URL={url}",
                                "-e",
                                "ARTIFACT_API_KEY=" + headers["Authorization"].removeprefix("Bearer "),
                                "-e",
                                f"ARTIFACT_UPLOAD_ROOTS={workspace}",
                                image,
                                *arguments,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            check=False,
                        )
                        assert_that(result.returncode, equal_to(0), result.stderr)
                        return json.loads(result.stdout)

                    output = cli("upload", workspace + "/report.csv")
                    artifact_id = output["artifact"]["id"]
                    assert_that(cli("list")["items"], has_length(1))
                    assert_that(
                        cli("link", artifact_id)["artifact"]["checksum"], equal_to(output["artifact"]["checksum"])
                    )
                    cli("retrieve", artifact_id, workspace + "/retrieved.csv")
                    assert_that((root / "retrieved.csv").read_bytes(), equal_to(CONTENT))
