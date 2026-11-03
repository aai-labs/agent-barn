import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import UUID

import pytest
from hamcrest import assert_that, empty, equal_to, greater_than_or_equal_to, has_items, is_not, less_than

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.domains.agents.builders.openclaw import build_config_map, build_openclaw_gateway_config
from api.domains.file_sync.models import FileSyncChangesCreate, FileSyncUploadCompleteCreate
from api.domains.file_sync.rules import SyncCategory, classify
from api.tests.core.givenpy import LambdaWith, given, then, when

AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
INGEST_KEY = "file-sync-contract-ingest-key"
SKILL_PATH = "workspace/skills/contract-skill/SKILL.md"
STUB = Path(__file__).parent / "fixtures" / "file_sync_ingest_stub.py"
MOUNTS = {"hermes": "/opt/data", "openclaw": "/home/node/.openclaw"}
NEVER_SYNCED = {
    "hermes": ["config.yaml", "aai-cli/key", ".env"],
    "openclaw": ["openclaw.json", "aai-cli/key"],
}
OFFERED = {
    "hermes": ["SOUL.md", "workspace/AGENTS.md", "workspace/IDENTITY.md", "workspace/TOOLS.md", "memories/USER.md"],
    "openclaw": ["workspace/SOUL.md", "workspace/AGENTS.md", "workspace/IDENTITY.md", "workspace/TOOLS.md"],
}
RUNTIME_STARTED = "runtime-started"
START_LIMIT_SECONDS = 120


def selected_image(runtime: str) -> str:
    name = f"{runtime.upper()}_TEST_IMAGE"
    image = os.environ.get(name)
    if not image:
        pytest.fail(f"{name} must name an already-built {runtime} image")
    subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)
    return image


def _runtime_is_present(runtime: str, image: str, root: Path):
    def step(context):
        context.runtime, context.image = runtime, image
        context.config_dir = root / "config"
        context.state_dir = root / "state"
        context.commands_dir = root / "commands"
        context.out_dir = root / "out"
        for directory in (root, context.config_dir, context.state_dir, context.commands_dir, context.out_dir):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o777)
        for rel in NEVER_SYNCED[runtime]:
            secret = context.state_dir / rel
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.parent.chmod(0o777)
            secret.write_text("never-synced-contract-secret")
            secret.chmod(0o666)

        def cleanup():
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    "0",
                    "--entrypoint",
                    "sh",
                    "-v",
                    f"{root}:/contract-root",
                    image,
                    "-c",
                    "chmod -R a+rwX /contract-root",
                ],
                check=False,
                capture_output=True,
            )

        return LambdaWith(lambda: None, cleanup)

    return step


def _runtime_is_configured():
    def step(context):
        skills = json.dumps([{"path": "contract-skill/SKILL.md", "content": "---\nname: contract-skill\n---\n"}])
        args = (AGENT_ID, ORG_ID, "agent-farm", "Soul.", "Identity.", "User.", "Tools.", "Agents.", "Boot.")
        if context.runtime == "hermes":
            config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_hermes_config_map(*args, "Heartbeat.", config, skills_json=skills)
            probe = "#!/bin/sh\ncat /contract-out/requests.jsonl 2>/dev/null | wc -l > /contract-out/runtime-started\n"
        else:
            config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_config_map(*args, "Bootstrap.", "Heartbeat.", config, skills_json=skills)
            probe = (
                '#!/bin/sh\ncase "$1" in\n'
                '  --version) echo "OpenClaw 2026.8.2" ;;\n'
                "  gateway) cat /contract-out/requests.jsonl 2>/dev/null | wc -l > /contract-out/runtime-started ;;\n"
                "  *) exit 0 ;;\nesac\n"
            )
        for name, content in config_map.data.items():
            target = context.config_dir / name
            target.write_text(content, newline="\n")
            target.chmod(0o644)
        shutil.copy(STUB, context.commands_dir / "file_sync_ingest_stub.py")
        wrapper = context.commands_dir / context.runtime
        wrapper.write_text(probe, newline="\n")
        wrapper.chmod(0o755)

    return step


def _start(context, *, ingest_up: bool) -> subprocess.CompletedProcess[str]:
    before_start = "python3 /contract-commands/file_sync_ingest_stub.py & "
    before_start += "while [ ! -f /tmp/file-sync-stub-ready ]; do sleep 0.1; done; "
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--entrypoint",
        "sh",
        "-v",
        f"{context.config_dir}:/app/config:ro",
        "-v",
        f"{context.state_dir}:{MOUNTS[context.runtime]}",
        "-v",
        f"{context.commands_dir}:/contract-commands:ro",
        "-v",
        f"{context.out_dir}:/contract-out",
        "-e",
        "PATH=/contract-commands:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "-e",
        "AGENTBARN_SCHEDULED_DELIVERY=0",
        "-e",
        "HERMES_HOME=/opt/data",
        "-e",
        f"AGENT_ID={AGENT_ID}",
        "-e",
        f"INGEST_URL=http://127.0.0.1:{18081 if ingest_up else 9}/ingest/v1",
        "-e",
        f"INGEST_API_KEY={INGEST_KEY}",
    ]
    if context.runtime == "hermes":
        workspace = context.state_dir / "workspace"
        workspace.mkdir(exist_ok=True)
        workspace.chmod(0o777)
        command += ["-v", f"{workspace}:/workspace"]
    command += [context.image, "-c", f"{before_start if ingest_up else ''}exec sh /app/config/start.sh"]
    started = time.monotonic()
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=START_LIMIT_SECONDS)
    context.elapsed = time.monotonic() - started
    return completed


def _requests(context) -> list[dict]:
    log = context.out_dir / "requests.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line]


def _runtime_started_after(context) -> int | None:
    marker = context.out_dir / RUNTIME_STARTED
    if not marker.exists():
        return None
    return int(marker.read_text().strip() or 0)


def file_sync_should_offer_the_agents_files_before_the_runtime_starts(runtime: str, image: str, root: Path) -> None:
    with given([_runtime_is_present(runtime, image, root), _runtime_is_configured()]) as context:
        with when("the generated start script runs in the pinned image with external networking disabled"):
            completed = _start(context, ingest_up=True)

        with then("the runtime starts after the helper's first round has finished"):
            assert_that(completed.returncode, equal_to(0), completed.stdout + completed.stderr)
            started_after = _runtime_started_after(context)
            assert started_after is not None, completed.stdout + completed.stderr
            first_round = _requests(context)[:started_after]
            assert_that([request["path"].rsplit("/", 1)[-1] for request in first_round[:1]], equal_to(["changes"]))
            assert_that(
                [request for request in first_round if request["path"].endswith("/operations")],
                is_not(empty()),
            )

        with then("the first report offers the Template files, the skills and the native memory"):
            report = FileSyncChangesCreate.model_validate(_requests(context)[0]["body"])
            reported = [entry.path for entry in report.entries]
            assert_that(reported, has_items(*OFFERED[runtime], SKILL_PATH))
            assert_that(report.complete, equal_to(True))

        with then("nothing the rules never sync is offered, and the secrets are absent"):
            assert_that([path for path in reported if classify(runtime, path) == SyncCategory.NEVER], equal_to([]))
            assert_that([path for path in NEVER_SYNCED[runtime] if path in reported], equal_to([]))

        with then("each offered file is uploaded without any credential and confirmed"):
            puts = [request for request in _requests(context) if request["method"] == "PUT"]
            assert_that({request["authorization"] for request in puts}, equal_to({None}))
            uploaded = {request["path"]: request["sha256"] for request in puts}
            by_path = {entry.path: entry.sha256 for entry in report.entries}
            assert_that({path: by_path[path] for path in uploaded}, equal_to(uploaded))
            confirmed = [
                FileSyncUploadCompleteCreate.model_validate(request["body"]).path
                for request in _requests(context)
                if request["path"].endswith("/uploads/complete")
            ]
            assert_that(confirmed, has_items(*OFFERED[runtime], SKILL_PATH))


def file_sync_should_never_block_the_runtime(runtime: str, image: str, root: Path) -> None:
    with given([_runtime_is_present(runtime, image, root), _runtime_is_configured()]) as context:
        with when("the generated start script runs while ingest cannot be reached"):
            completed = _start(context, ingest_up=False)

        with then("the runtime still starts"):
            assert_that(completed.returncode, equal_to(0), completed.stdout + completed.stderr)
            assert_that(_runtime_started_after(context), greater_than_or_equal_to(0))
            assert_that(context.elapsed, less_than(START_LIMIT_SECONDS))
