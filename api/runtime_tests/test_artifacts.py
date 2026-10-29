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
from uuid import uuid4

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
        yield f"http://127.0.0.1:{server.server_port}/api/v1/agent-artifacts/runtime"
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
                context.agent.agent_type = runtime
                headers = runtime_auth(context)
                root = Path(directory)
                root.chmod(0o777)
                (root / "agentbarn_artifacts.py").write_text(ARTIFACT_TOOL)
                (root / "agent-trigger-server.py").write_text(
                    (Path(__file__).parents[1] / "domains/agents/scripts/agent-trigger-server.py").read_text()
                )
                (root / "agentbarn-artifacts").write_text(ARTIFACT_COMMAND)
                (root / "agentbarn-artifacts").chmod(0o555)
                (root / "report.csv").write_bytes(CONTENT)
                workspace = "/workspace" if runtime == "hermes" else "/home/node/.openclaw/workspace"
                with product_listener(context.client) as url:

                    def cli(*arguments, probe=None):
                        result = subprocess.run(
                            [
                                "docker",
                                "run",
                                "--rm",
                                "--network",
                                "host",
                                "--entrypoint",
                                "python3" if probe else "/usr/local/bin/agentbarn-artifacts",
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
                                *(["-c", probe] if probe else arguments),
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

                    # Deterministic file steps execute real retrieval and publication inside each image.
                    # This proves the byte pipeline, not live model/tool selection.
                    from api.domains.workflows.runtime_service import WorkflowRuntimeService
                    from api.tests.helpers.workflows import draft
                    from api.tests.integration.test_workflow_runs import attempt, result, start
                    from api.tests.integration.test_workflows import auth, base

                    body = draft()
                    body["inputs"][0]["type"] = "file"
                    body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Transform output"})
                    saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=body).json()
                    started, _, _ = start(
                        context,
                        saved,
                        inputs={
                            "period": {
                                "artifact_id": artifact_id,
                                "checksum": output["artifact"]["checksum"],
                            }
                        },
                    )
                    assert started.status_code == 202, started.text
                    previous_id = artifact_id
                    expected = CONTENT
                    for index in range(2):
                        repository, current, token = attempt(context, started.json()["id"])
                        handoff = context.injector.get(WorkflowRuntimeService).handoff(current.id, token)
                        probe = f"""
import importlib.util, json, pathlib, subprocess, tempfile
spec = importlib.util.spec_from_file_location('trigger', '/app/config/agent-trigger-server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(dir={workspace!r}) as directory:
    files = module._retrieve_workflow_files({handoff["files"]!r}, directory, {str(current.id)!r})
    source = next(file for file in files if file['artifact_id'] == {previous_id!r})
    content = pathlib.Path(source['path']).read_bytes() + {f"step-{index + 1}\n".encode()!r}
    target = pathlib.Path({workspace!r}) / 'deliverable-{index}.csv'
    target.write_bytes(content)
    completed = subprocess.run(['/usr/local/bin/agentbarn-artifacts', 'upload', str(target), '--attempt-id', {str(current.id)!r}], capture_output=True, text=True, check=True)
    print(completed.stdout)
"""
                        delivered = cli(probe=probe)["artifact"]
                        expected += f"step-{index + 1}\n".encode()
                        assert (root / f"deliverable-{index}.csv").read_bytes() == expected
                        repository.complete(current.id, token, result())
                        previous_id = delivered["id"]
                    detail = context.client.get(
                        base(context) + f"/workflow-runs/{started.json()['id']}", headers=auth(context)
                    ).json()
                    assert detail["state"] == "SUCCEEDED"
                    assert detail["final_artifacts"][0]["artifact_id"] == previous_id
                    cli("retrieve", previous_id, workspace + "/final.csv", "--checksum", delivered["checksum"])
                    assert (root / "final.csv").read_bytes() == expected
