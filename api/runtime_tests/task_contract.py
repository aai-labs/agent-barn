"""Shared contract: each runtime image runs the generated Task command from the Agent's own shell."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hamcrest import assert_that, contains_string, equal_to, has_entries

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.domains.agents.builders.openclaw import build_config_map, build_openclaw_gateway_config
from api.domains.agents.builders.tasks import TASK_TOOL_INSTRUCTIONS
from api.runtime_tests.memory_helpers import AGENT_ID, ORG_ID, runtime_is_present
from api.tests.core.givenpy import LambdaWith, given, then, when

TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"
INGEST_KEY = "task-contract-ingest-key"
REFUSAL = "The file is larger than the space left for this Organization's Task Files."
FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "agent_tasks"
HERMES_PLUGIN_HOOKS = ["on_session_end", "post_tool_call", "pre_llm_call", "pre_verify", "transform_tool_result"]
# Turn hooks need allowConversationAccess; without it OpenClaw drops them with only a warning.
OPENCLAW_PLUGIN_HOOKS = ["after_tool_call", "agent_end", "before_agent_finalize", "before_prompt_build"]


def _ingest_stub_is_ready():
    def step(context):
        context.requests = []

        class Handler(BaseHTTPRequestHandler):
            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                context.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": body.decode(errors="replace"),
                    }
                )
                code, payload = self.answer()
                encoded = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def answer(self) -> tuple[int, object]:
                if "filename=too-big.csv" in self.path:
                    return 400, {"detail": REFUSAL}
                if self.command == "GET" and self.path.split("?")[0].endswith("/tasks"):
                    return 200, {"items": [{"id": TASK_ID, "title": "Reconcile invoices"}], "total": 1}
                if self.command == "GET":
                    return 200, {"id": TASK_ID, "notes": [], "files": []}
                if self.command == "POST":
                    return 201, {"id": TASK_ID}
                return 200, {"id": TASK_ID, "status": "in_progress"}

            do_GET = do_POST = do_PATCH = respond

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        context.ingest_url = f"http://127.0.0.1:{server.server_port}/ingest/v1"

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()

        return LambdaWith(thread.start, cleanup)

    return step


def _tasks_are_configured():
    def step(context):
        args = (AGENT_ID, ORG_ID, "agent-farm", "Test soul.", "Test identity.", "Template user.", "Test tools.")
        if context.runtime == "hermes":
            config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_hermes_config_map(*args, "Test agents.", "", "", config)
            driver = "hermes_task_driver.py"
            command = f"#!/bin/sh\nexec python3 /contract-commands/{driver} {TASK_ID}\n"
        else:
            config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_config_map(*args, "Test agents.", "", "", "", config)
            driver = "openclaw_task_driver.mjs"
            command = (
                '#!/bin/sh\ncase "$1" in\n'
                '  --version) echo "OpenClaw 2026.8.2" ;;\n'
                f"  gateway) exec node /contract-commands/{driver} {TASK_ID} ;;\n  *) exit 0 ;;\nesac\n"
            )
        for name, content in config_map.data.items():
            target = context.config_dir / name
            target.write_text(content)
            target.chmod(0o555 if name == "agentbarn-task" else 0o644)
        shutil.copy(FIXTURES / driver, context.commands_dir / driver)
        wrapper = context.commands_dir / context.runtime
        wrapper.write_text(command)
        wrapper.chmod(0o755)

    return step


def _start(context) -> None:
    mount = "/opt/data" if context.runtime == "hermes" else "/home/node/.openclaw"
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "host",
        "--entrypoint",
        "sh",
        "-v",
        f"{context.config_dir}:/app/config:ro",
        "-v",
        f"{context.config_dir / 'agentbarn-task'}:/usr/local/bin/agentbarn-task:ro",
        "-v",
        f"{context.state_dir}:{mount}",
        "-v",
        f"{context.commands_dir}:/contract-commands:ro",
        "-e",
        "PATH=/contract-commands:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "-e",
        "AGENTBARN_SCHEDULED_DELIVERY=0",
        "-e",
        "HERMES_HOME=/opt/data",
        "-e",
        f"AGENT_ID={AGENT_ID}",
        "-e",
        f"INGEST_URL={context.ingest_url}",
        "-e",
        f"INGEST_API_KEY={INGEST_KEY}",
        "-e",
        "TASK_FILE_MAX_BYTES=1048576",
    ]
    if context.runtime == "hermes":
        workspace = context.state_dir / "workspace"
        workspace.mkdir(exist_ok=True)
        workspace.chmod(0o777)
        command += ["-v", f"{workspace}:/workspace"]
    command += [context.image, "/app/config/start.sh"]
    context.completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=180)
    context.result = {}
    for line in context.completed.stdout.splitlines():
        if line.startswith("TASK_RUNTIME_CONTRACT="):
            context.result = json.loads(line.removeprefix("TASK_RUNTIME_CONTRACT="))


def tasks_should_be_recorded_from_the_agents_shell(runtime: str, image: str, root: Path) -> None:
    with given([runtime_is_present(runtime, image, root), _ingest_stub_is_ready(), _tasks_are_configured()]) as context:
        with when("the started runtime runs the Task command from its own shell"):
            _start(context)

        with then("the command is installed, authenticated with the Agent's key, and reports refusals"):
            output = context.completed.stdout + context.completed.stderr
            assert_that(bool(context.result), equal_to(True), output)
            assert_that(context.result["instructions"], contains_string(TASK_TOOL_INSTRUCTIONS.strip()))
            results = context.result["results"]
            for name in ("discover", "create", "status", "note", "attach", "list", "show"):
                assert_that(results[name]["exit_code"], equal_to(0), f"{name}: {results[name]}")
            assert_that(results["refused"]["exit_code"], equal_to(1), str(results["refused"]))
            assert_that(results["refused"]["output"], contains_string(REFUSAL))
            tasks = f"/ingest/v1/agents/{AGENT_ID}/tasks"
            # Other plugins loaded alongside (telemetry) post to the same stub; only Task calls matter here.
            task_requests = [request for request in context.requests if request["path"].startswith(tasks)]
            assert_that({request["authorization"] for request in task_requests}, equal_to({f"Bearer {INGEST_KEY}"}))
            calls = [(request["method"], request["path"]) for request in task_requests]
            assert_that(
                calls,
                equal_to(
                    [
                        ("POST", tasks),
                        ("PATCH", f"{tasks}/{TASK_ID}"),
                        ("POST", f"{tasks}/{TASK_ID}/notes"),
                        ("POST", f"{tasks}/{TASK_ID}/files?filename=report.csv"),
                        ("POST", f"{tasks}/{TASK_ID}/files?filename=too-big.csv"),
                        ("GET", f"{tasks}?status=open"),
                        ("GET", f"{tasks}/{TASK_ID}"),
                        ("POST", tasks),
                    ]
                ),
            )
            note, upload, from_plugin = task_requests[2], task_requests[3], task_requests[-1]
            assert_that(json.loads(note["body"]), has_entries(body="Matched 40 of 42 invoices"))
            assert_that((upload["content_type"], upload["body"]), equal_to(("text/csv", "invoice,amount\n1,10\n")))
            assert_that(json.loads(from_plugin["body"]), equal_to({"title": "From the plugin"}))

        with then("the agentbarn-tasks plugin loads through the runtime's own loader and offers its tool"):
            plugin = context.result["plugin"]
            assert_that(plugin["tool_result"], has_entries(id=TASK_ID), str(plugin))
            if context.runtime == "hermes":
                assert_that(plugin["hooks"], equal_to(HERMES_PLUGIN_HOOKS), str(plugin))
                assert_that(plugin["offered"], equal_to({"slack": True, "api_server": True}), str(plugin))
                assert_that(plugin["tools"], equal_to(["agentbarn_task"]), str(plugin))
                # Deferred behind tool search, the model has to look the tool up first and skips it.
                assert_that(plugin["tool_search"], equal_to("off"), str(plugin))
            else:
                assert_that((plugin["status"], plugin["error"]), equal_to(("loaded", None)), str(plugin))
                assert_that(plugin["hooks"], equal_to(OPENCLAW_PLUGIN_HOOKS), str(plugin))
                assert_that(plugin["tool_names"], equal_to(["agentbarn_task"]), str(plugin))
