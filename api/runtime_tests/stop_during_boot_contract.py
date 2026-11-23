import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4

from hamcrest import assert_that, equal_to, less_than

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
)
from api.domains.agents.builders.common import container_resources
from api.domains.agents.builders.hermes import (
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
)
from api.domains.agents.builders.openclaw import build_config_map, build_deployment, build_openclaw_gateway_config
from api.tests.core.givenpy import LambdaWith, given, then, when

AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
NAMESPACE = "agent-farm"
MOUNTS = {"hermes": "/opt/data", "openclaw": "/home/node/.openclaw"}
PROBES = {
    "hermes": "#!/bin/sh\nexec sleep 300\n",
    "openclaw": (
        '#!/bin/sh\ncase "$1" in\n'
        '  --version) echo "OpenClaw 2026.8.2" ;;\n'
        "  gateway) exec sleep 300 ;;\n"
        "  *) exit 0 ;;\nesac\n"
    ),
}
SETUP_STEP = b"/app/config/memory-gateway-ready.py"
SETUP_WAIT_SECONDS = 90
STOP_GRACE_SECONDS = 10
STOP_LIMIT_SECONDS = 5
RESOURCES = container_resources(
    cpu_request_millicores=STANDARD_CPU_REQUEST_MILLICORES,
    cpu_limit_millicores=STANDARD_CPU_LIMIT_MILLICORES,
    memory_request_bytes=STANDARD_MEMORY_REQUEST_BYTES,
    memory_limit_bytes=STANDARD_MEMORY_LIMIT_BYTES,
)


def _runtime_is_present(runtime: str, image: str, root: Path):
    def step(context):
        context.runtime, context.image = runtime, image
        context.container = f"stop-during-boot-{uuid4().hex[:12]}"
        context.config_dir = root / "config"
        context.state_dir = root / "state"
        context.commands_dir = root / "commands"
        for directory in (root, context.config_dir, context.state_dir, context.commands_dir):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o777)

        def cleanup():
            subprocess.run(["docker", "rm", "-f", context.container], check=False, capture_output=True)
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
        args = (AGENT_ID, ORG_ID, NAMESPACE, "Soul.", "Identity.", "User.", "Tools.", "Agents.", "Boot.")
        if context.runtime == "hermes":
            config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_hermes_config_map(*args, "Heartbeat.", config)
            deployment = build_hermes_deployment(AGENT_ID, ORG_ID, NAMESPACE, context.image, resources=RESOURCES)
        else:
            config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
            config_map = build_config_map(*args, "Bootstrap.", "Heartbeat.", config)
            deployment = build_deployment(AGENT_ID, ORG_ID, NAMESPACE, context.image, resources=RESOURCES)
        context.command = deployment.spec.template.spec.containers[0].command
        for name, content in config_map.data.items():
            target = context.config_dir / name
            target.write_text(content, newline="\n")
            target.chmod(0o644)
        probe = context.commands_dir / context.runtime
        probe.write_text(PROBES[context.runtime], newline="\n")
        probe.chmod(0o755)

    return step


def _boot(context) -> None:
    command = [
        "docker",
        "run",
        "--detach",
        "--pull=never",
        "--network=none",
        "--name",
        context.container,
        "--entrypoint",
        context.command[0],
        "-v",
        f"{context.config_dir}:/app/config:ro",
        "-v",
        f"{context.state_dir}:{MOUNTS[context.runtime]}",
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
        "INGEST_URL=http://127.0.0.1:9/ingest/v1",
        "-e",
        "INGEST_API_KEY=stop-during-boot-ingest-key",
        "-e",
        "MEMORY_URL=http://127.0.0.1:9",
        "-e",
        "MEMORY_API_KEY=stop-during-boot-memory-key",
    ]
    if context.runtime == "hermes":
        workspace = context.state_dir / "workspace"
        workspace.mkdir(exist_ok=True)
        workspace.chmod(0o777)
        command += ["-v", f"{workspace}:/workspace"]
    command += [context.image, *context.command[1:]]
    subprocess.run(command, check=True, capture_output=True)


def _in_setup(context) -> bool:
    deadline = time.monotonic() + SETUP_WAIT_SECONDS
    while time.monotonic() < deadline:
        processes = subprocess.run(
            ["docker", "exec", context.container, "sh", "-c", "cat /proc/[0-9]*/cmdline"],
            check=False,
            capture_output=True,
        )
        if SETUP_STEP in processes.stdout:
            return True
        time.sleep(0.2)
    return False


def _logs(context) -> str:
    logs = subprocess.run(["docker", "logs", context.container], check=False, capture_output=True, text=True)
    return logs.stdout + logs.stderr


def stop_should_end_the_container_while_start_sh_is_in_setup(runtime: str, image: str, root: Path) -> None:
    with given([_runtime_is_present(runtime, image, root), _runtime_is_configured()]) as context:
        with when("the generated Deployment command boots the pinned image and setup waits on the memory gateway"):
            _boot(context)
            in_setup = _in_setup(context)

        with then("start.sh is still in setup"):
            assert_that(in_setup, equal_to(True), _logs(context))

        with when("the container is stopped the way the kubelet stops it"):
            started = time.monotonic()
            subprocess.run(
                ["docker", "stop", "--time", str(STOP_GRACE_SECONDS), context.container],
                check=True,
                capture_output=True,
            )
            elapsed = time.monotonic() - started

        with then("it ends on SIGTERM instead of waiting out the grace period"):
            assert_that(elapsed, less_than(STOP_LIMIT_SECONDS), _logs(context))
