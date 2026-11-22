"""SSH-disabled startup must not depend on packages absent from older images."""

import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import docker
from hamcrest import assert_that, contains_string, equal_to

from api.runtime_tests.memory_helpers import selected_image
from api.tests.core.givenpy import given, then, when

_SCRIPTS = Path(__file__).parents[1] / "domains/agents/scripts"


def an_unkeyed_parent_uses_an_older_runtime(runtime, root, manifest):
    def step(context):
        context.image = selected_image(runtime)
        root.chmod(0o755)
        (root / "ssh-agent-relay.py").write_text((_SCRIPTS / "ssh-agent-relay.py").read_text())
        bots = [] if manifest == "empty" else [{"id": str(uuid4())}]
        (root / "bots.json").write_text(json.dumps({"bots": bots}))
        (root / "websockets.py").write_text('raise RuntimeError("SSH discovery must use only the standard library")\n')
        source = (_SCRIPTS / runtime / "start.sh").read_text()
        start = source.index("\nif ", source.index("file-sync.py &"))
        end = source.index("\nfi", start) + len("\nfi")
        context.script = source[start:end] + "\nprintf gateway-ready"
        context.root = root

    return step


def run_startup_without_ssh_packages(context):
    with closing(docker.from_env()) as client:
        container = client.containers.run(
            context.image,
            ["-ec", context.script],
            entrypoint="sh",
            detach=True,
            environment={"AGENTBARN_SSH_SIGNER_TOKEN": "", "SSH_ENABLED": "false", "PYTHONPATH": "/app/config"},
            volumes={str(context.root): {"bind": "/app/config", "mode": "ro"}},
            # Emulate pre-SSH images, including a system Python without relay dependencies.
            tmpfs={"/opt/agentbarn-ssh": "rw", "/run/agentbarn/bots": "rw"},
        )
        try:
            result = container.wait(timeout=30)
            return result["StatusCode"], container.logs().decode()
        finally:
            container.remove(force=True)


def ssh_disabled_should_start(runtime, manifest, tmp_path):
    with given([an_unkeyed_parent_uses_an_older_runtime(runtime, tmp_path, manifest)]) as context:
        with when("startup runs with no Parent or Bot signing credentials"):
            status, output = run_startup_without_ssh_packages(context)
        with then("startup reaches the gateway without the optional SSH interpreter"):
            assert_that(status, equal_to(0), output)
            assert_that(output, contains_string("gateway-ready"))
