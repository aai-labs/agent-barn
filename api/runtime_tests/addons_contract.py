"""Prove Agent Add-ons install and work inside the pinned runtime images.

Builds the real Deployment, then runs its `fix-pvc-owner` and `install-addons` init containers
as the spec gives them (image, user, command, mounts) against a fresh Docker volume, and checks
from the agent container's side, read-only mount and environment included, that every kind is
usable by the runtime user and cannot be changed by it. The installs reach PyPI, npm and
GitHub, as an Agent's pod does.
"""

import json
import os
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, starts_with

from api.domains.agent_addons.models import AgentAddonKind, ApprovedAddon
from api.domains.agents.builders import build_deployment, build_hermes_deployment, container_resources
from api.domains.agents.builders.addons import (
    ADDONS_CONFIG_DIR,
    ADDONS_DIR,
    HERMES_RUNTIME_UID,
    INSTALL_ADDONS_CONTAINER,
    OPENCLAW_RUNTIME_UID,
    addons_agent_env,
    build_addons_config_map,
)
from api.tests.core.givenpy import LambdaWith, given, then, when

HUMANIZE = ApprovedAddon(uuid.uuid7(), AgentAddonKind.PIP, "humanize", {"version": "4.12.3"}, "Formatting.")
LEFT_PAD = ApprovedAddon(uuid.uuid7(), AgentAddonKind.NPM, "left-pad", {"version": "1.3.0"}, "Padding.")
HELLO_COMMIT = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"
HELLO_REPO = ApprovedAddon(
    uuid.uuid7(),
    AgentAddonKind.GIT,
    "hello-world",
    {"url": "https://github.com/octocat/Hello-World.git", "commit": HELLO_COMMIT},
    "A repository checked out at one commit.",
)
_README_URL = f"https://raw.githubusercontent.com/octocat/Hello-World/{HELLO_COMMIT}/README"
_README_SHA256 = "03ba204e50d126e4674c005e04d82e84c21366780af1f43bd54a37816b6ab340"
HELLO_FILE = ApprovedAddon(
    uuid.uuid7(), AgentAddonKind.BINARY, "hello-readme", {"url": _README_URL, "sha256": _README_SHA256}, "A file."
)
GREETER = ApprovedAddon(
    uuid.uuid7(),
    AgentAddonKind.COMMAND,
    "greeter",
    {"command": 'printf "#!/bin/sh\\necho greetings\\n" > "$ADDONS_DIR/bin/greet"\nchmod +x "$ADDONS_DIR/bin/greet"'},
    "A reviewed command.",
)
EVERY_KIND = [HUMANIZE, LEFT_PAD, HELLO_REPO, HELLO_FILE, GREETER]

_RESOURCES = container_resources(
    cpu_request_millicores=500,
    cpu_limit_millicores=2000,
    memory_request_bytes=1024**3,
    memory_limit_bytes=2 * 1024**3,
)
_UIDS = {"hermes": HERMES_RUNTIME_UID, "openclaw": OPENCLAW_RUNTIME_UID}
_SCRIPTS = Path(__file__).resolve().parent.parent / "domains" / "agents" / "scripts"
# Commands every runtime image has, which an add-on must never replace.
_IMAGE_COMMANDS = ("node", "python3", "git")


@dataclass
class Install:
    returncode: int
    output: str
    termination: dict | None


def _docker(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)


def runtime_image_is_built(runtime: str):
    def step(context) -> None:
        image_variable = f"{runtime.upper()}_TEST_IMAGE"
        image = os.environ.get(image_variable)
        if not image:
            pytest.fail(f"{image_variable} must name an already-built {runtime} image")
        subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=True)
        context.runtime = runtime
        context.image = image

    return step


def addons_volume_is_fresh(root: Path):
    def step(context):
        context.root = root
        context.volume = f"addons-contract-{uuid.uuid4().hex[:12]}"
        context.data_volume = f"{context.volume}-data"
        context.termination = root / "termination"
        context.termination.mkdir()
        context.termination.chmod(0o777)

        def create():
            for volume in (context.volume, context.data_volume):
                assert _docker("volume", "create", volume).returncode == 0

        def remove():
            _docker("volume", "rm", "-f", context.volume, context.data_volume)

        return LambdaWith(create, remove)

    return step


def _deployment(context):
    build = build_hermes_deployment if context.runtime == "hermes" else build_deployment
    return build(uuid.uuid7(), uuid.uuid7(), "agent-farm", context.image, resources=_RESOURCES, addons=True)


def _mount(container, source: str, read_only: bool = False) -> list[str]:
    return ["--mount", f"type=volume,src={source},dst={container}{',readonly' if read_only else ''}"]


def owner_fix_has_run(context) -> None:
    """The root `fix-pvc-owner` init container, as built, which hands /opt/addons over."""
    fix = _deployment(context).spec.template.spec.init_containers[0]
    data_path = next(m.mount_path for m in fix.volume_mounts if m.name == "data")
    result = _docker(
        "run",
        "--rm",
        "--pull=never",
        "--user",
        "0",
        *_mount(data_path, context.data_volume),
        *_mount(ADDONS_DIR, context.volume),
        "--entrypoint",
        fix.command[0],
        context.image,
        *fix.command[1:],
    )
    assert_that(result.returncode, equal_to(0), result.stderr)


def install(context, addons: list[ApprovedAddon]) -> Install:
    """`install-addons`, as built: its image, user, command, environment and two mounts."""
    container = next(
        c for c in _deployment(context).spec.template.spec.init_containers if c.name == INSTALL_ADDONS_CONTAINER
    )
    config = context.root / f"config-{uuid.uuid4().hex[:8]}"
    config.mkdir()
    for name, content in build_addons_config_map(
        uuid.uuid7(), uuid.uuid7(), "agent-farm", image=context.image, addons=addons
    ).data.items():
        (config / name).write_text(content)
        (config / name).chmod(0o644)
    config.chmod(0o755)
    termination = context.termination / "log"
    termination.unlink(missing_ok=True)
    env = [arg for var in container.env for arg in ("--env", f"{var.name}={var.value}")]
    user = container.security_context.run_as_user
    result = _docker(
        "run",
        "--rm",
        "--pull=never",
        "--user",
        f"{user}:{user}",
        *env,
        # Stands in for /dev/termination-log, which only the kubelet provides.
        "--env",
        "ADDONS_TERMINATION_LOG=/termination/log",
        "--mount",
        f"type=bind,src={context.termination},dst=/termination",
        *_mount(ADDONS_DIR, context.volume),
        "--mount",
        f"type=bind,src={config},dst={ADDONS_CONFIG_DIR},readonly",
        "--entrypoint",
        container.command[0],
        context.image,
        *container.command[1:],
    )
    return Install(
        result.returncode,
        result.stdout + result.stderr,
        json.loads(termination.read_text()) if termination.exists() else None,
    )


def as_the_agent(context, script: str) -> subprocess.CompletedProcess:
    """A shell in the agent container: its default user, the add-ons volume read-only, its
    add-on environment, and PATH set by start.sh's own add-ons lines."""
    env = [arg for var in addons_agent_env() for arg in ("--env", f"{var.name}={var.value}")]
    return _docker(
        "run",
        "--rm",
        "--pull=never",
        *env,
        *_mount(ADDONS_DIR, context.volume, read_only=True),
        "--entrypoint",
        "/bin/bash",
        context.image,
        "-c",
        f"{_start_sh_addons_path(context.runtime)}\n{script}",
        timeout=120,
    )


def _start_sh_addons_path(runtime: str) -> str:
    """The `if [ -n "${AGENTBARN_ADDONS_PATH:-}" ] ... fi` block of the runtime's start.sh."""
    lines = (_SCRIPTS / runtime / "start.sh").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if "AGENTBARN_ADDONS_PATH:-" in line)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[start : end + 1])


def _check(context, script: str) -> str:
    result = as_the_agent(context, script)
    assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
    return result.stdout.strip()


def every_kind_should_install_and_be_usable(runtime: str, root: Path) -> None:
    with given([runtime_image_is_built(runtime), addons_volume_is_fresh(root)]) as context:
        with then("the install container's user is the image's own runtime user"):
            uid = _docker("run", "--rm", "--pull=never", "--entrypoint", "id", context.image, "-u")
            assert_that(int(uid.stdout.strip()), equal_to(_UIDS[runtime]))

        with when("the Agent starts with one add-on of every kind approved"):
            owner_fix_has_run(context)
            result = install(context, EVERY_KIND)

        with then("every add-on installs"):
            assert_that(result.returncode, equal_to(0), result.output)
            assert_that(result.output, contains_string("5 add-on(s) installed"))

        with then("the pip package imports from the runtime's own Python"):
            path = _check(context, 'python3 -c "import humanize; print(humanize.__file__)"')
            assert_that(path, starts_with(f"{ADDONS_DIR}/python/"))

        with then("the npm package loads in Node"):
            assert_that(_check(context, "node -e \"console.log(require('left-pad')('7', 3, '0'))\""), equal_to("007"))

        with then("the repository is checked out at its commit"):
            assert_that(_check(context, f"git -C {ADDONS_DIR}/src/hello-world rev-parse HEAD"), equal_to(HELLO_COMMIT))

        with then("the checksummed download is on PATH"):
            assert_that(_check(context, 'cat "$(command -v hello-readme)"'), equal_to("Hello World!"))

        with then("what the reviewed command installed runs"):
            assert_that(_check(context, "greet"), equal_to("greetings"))

        with then("the runtime itself still starts its Python with the add-ons beside it"):
            if runtime == "hermes":
                _check(context, 'python3 -c "import hermes_cli"')
            else:
                _check(context, "openclaw --version")

        with then("the agent cannot change what was installed"):
            attempts = as_the_agent(
                context,
                " ; ".join(
                    f"{command} 2>/dev/null && echo CHANGED || echo REFUSED"
                    for command in (
                        f"touch {ADDONS_DIR}/python/planted.py",
                        f"rm -f {ADDONS_DIR}/bin/greet",
                        f"chmod 777 {ADDONS_DIR}/bin",
                    )
                ),
            )
            assert_that(attempts.stdout.split(), equal_to(["REFUSED"] * 3))

        with when("the Agent starts again with nothing changed"):
            again = install(context, EVERY_KIND)

        with then("nothing is installed again"):
            assert_that(again.returncode, equal_to(0), again.output)
            assert_that(again.output, contains_string("nothing to do"))


def an_add_on_should_not_replace_a_runtime_command(runtime: str, root: Path) -> None:
    with given([runtime_image_is_built(runtime), addons_volume_is_fresh(root)]) as context:
        impostors = ApprovedAddon(
            uuid.uuid7(),
            AgentAddonKind.COMMAND,
            "impostors",
            {
                "command": "\n".join(
                    f'printf "#!/bin/sh\\necho REPLACED\\n" > "$ADDONS_DIR/bin/{name}" && chmod +x "$ADDONS_DIR/bin/{name}"'
                    for name in _IMAGE_COMMANDS
                )
            },
            "Commands named after the image's own.",
        )
        owner_fix_has_run(context)

        with when("an add-on puts commands named after the image's own into its bin"):
            result = install(context, [impostors])
            assert_that(result.returncode, equal_to(0), result.output)

        with then("the agent still runs the image's own"):
            for name in _IMAGE_COMMANDS:
                path = _check(context, f"command -v {name}")
                assert_that(path.startswith(ADDONS_DIR), equal_to(False), f"{name} resolved to {path}")
            assert_that(_check(context, "node -e 'console.log(7)'"), equal_to("7"))


def a_checksum_mismatch_should_fail_the_install(runtime: str, root: Path) -> None:
    with given([runtime_image_is_built(runtime), addons_volume_is_fresh(root)]) as context:
        tampered = HELLO_FILE._replace(spec={"url": _README_URL, "sha256": "0" * 64})
        owner_fix_has_run(context)

        with when("the download does not match the approved SHA-256"):
            result = install(context, [GREETER, tampered])

        with then("the install fails naming that add-on, and leaves nothing the agent could use"):
            assert_that(result.returncode, equal_to(1), result.output)
            assert_that(result.termination, equal_to({"addon_id": str(tampered.id), "reason": "checksum"}))
            missing = as_the_agent(
                context, f"test -e {ADDONS_DIR}/bin/hello-readme || test -e {ADDONS_DIR}/.agentbarn-addons-hash"
            )
            assert_that(missing.returncode, equal_to(1), shlex.join(["stdout", missing.stdout]))
