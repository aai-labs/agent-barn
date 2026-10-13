"""Owns a disposable k3d cluster; never uses the developer's Kubernetes context or service credentials."""

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

K3S_IMAGE = "rancher/k3s:v1.31.5-k3s1"


def command(args: list[str], *, stdin: str | None = None, timeout: int = 300) -> str:
    result = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        # Inputs may contain fixture Secrets; never include them in an exception.
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}): {result.stderr[-2000:]}")
    return result.stdout


@dataclass
class Cluster:
    kubeconfig: Path
    namespace: str = "isolation-contract"
    users: dict[str, tuple[int, int]] = field(default_factory=dict)

    def kubectl(self, *args: str, stdin: str | None = None, timeout: int = 300) -> str:
        return command(
            ["kubectl", "--kubeconfig", str(self.kubeconfig), "--namespace", self.namespace, *args],
            stdin=stdin,
            timeout=timeout,
        )

    def apply(self, *resources: dict) -> None:
        self.kubectl("apply", "-f", "-", stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": resources}))


@pytest.fixture(scope="session")
def cluster(tmp_path_factory):
    runtime = os.environ.get("ISOLATION_TEST_RUNTIME", "both")
    if runtime not in {"both", "hermes", "openclaw"}:
        pytest.fail("ISOLATION_TEST_RUNTIME must be both, hermes or openclaw")
    runtimes = ("hermes", "openclaw") if runtime == "both" else (runtime,)
    images = []
    users = {}
    for selected in runtimes:
        image = os.environ.get(f"{selected.upper()}_TEST_IMAGE")
        if not image:
            pytest.fail(f"{selected.upper()}_TEST_IMAGE must name a locally built runtime image")
        command(["docker", "image", "inspect", image])
        identity = (
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--entrypoint",
                    "python3",
                    image,
                    "-c",
                    "import os; print(os.getuid(), os.getgid())",
                ]
            )
            .strip()
            .split()
        )
        uid, gid = map(int, identity)
        if uid == 0:
            pytest.fail("Runtime contract requires an image with a non-root USER")
        users[selected] = (uid, gid)
        images.append(image)
    name = "isolation-" + uuid.uuid4().hex[:10]
    root = tmp_path_factory.mktemp("isolation-cluster")
    kubeconfig = root / "kubeconfig.yaml"
    try:
        command(
            [
                "k3d",
                "cluster",
                "create",
                name,
                "--image",
                K3S_IMAGE,
                "--kubeconfig-update-default=false",
                "--kubeconfig-switch-context=false",
                "--wait",
                "--timeout",
                "180s",
            ],
            timeout=240,
        )
        kubeconfig.write_text(command(["k3d", "kubeconfig", "get", name]))
        kubeconfig.chmod(0o600)
        command(["k3d", "image", "import", *dict.fromkeys(images), "--cluster", name], timeout=600)
        selected_cluster = Cluster(kubeconfig, users=users)
        selected_cluster.kubectl("create", "namespace", selected_cluster.namespace)
        yield selected_cluster
    finally:
        command(["k3d", "cluster", "delete", name], timeout=120)
