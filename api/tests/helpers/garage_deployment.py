"""Disposable verification of the production local-development Compose/bootstrap files."""

import json
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from api.scripts.provision_garage import ROOT, local_compose, read_env
from api.tests.helpers.artifacts import registered_compose_storage


@contextmanager
def persistent_garage():
    with tempfile.TemporaryDirectory(prefix="agentbarn-garage-deployment-") as temporary:
        directory = Path(temporary) / "garage"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        command = [
            sys.executable,
            str(ROOT / "api/scripts/provision_garage.py"),
            "up",
            "--state-dir",
            str(directory),
            "--port",
            str(port),
            "--endpoint",
            f"http://127.0.0.1:{port}",
        ]
        compose = None
        try:
            result = subprocess.run(command, capture_output=True, check=False, timeout=150)
            if result.returncode:
                raise RuntimeError("Persistent Garage test bootstrap failed")
            state = json.loads((directory / "state.json").read_text())
            compose = local_compose(directory, state)
            environment = read_env(directory / "application.env")
            with registered_compose_storage(environment, compose):
                yield environment, compose, command
        finally:
            if compose is None and (directory / "state.json").exists():
                compose = local_compose(directory, json.loads((directory / "state.json").read_text()))
            if compose is not None:
                subprocess.run([*compose, "down", "--volumes"], capture_output=True, check=False, timeout=90)


def import_garage_test_images(cluster: str, directory: Path) -> None:
    """Import only the host platform; k3d can report success after a missing digest."""
    from api.scripts.provision_garage import run

    if not cluster.startswith("af415-garage-"):
        raise ValueError("Image preparation is limited to disposable AF-415 clusters")
    nodes = run(["docker", "ps", "--filter", f"name=k3d-{cluster}-", "--format", "{{.Names}}"]).stdout.splitlines()
    if len(nodes) != 3 or not all(node.startswith(f"k3d-{cluster}-") for node in nodes):
        raise RuntimeError("Expected three owned test nodes before importing storage images")
    for image in ("dxflrs/garage:v2.4.1", "rancher/mirrored-library-busybox:1.36.1"):
        if run(["docker", "image", "inspect", image], check=False).returncode:
            run(["docker", "pull", image], timeout=300)
        platform = run(["docker", "image", "inspect", image, "--format", "{{.Os}}/{{.Architecture}}\n"]).stdout.strip()
        archive = directory / "storage-image.tar"
        try:
            with archive.open("wb") as target:
                result = subprocess.run(
                    ["docker", "image", "save", image], stdout=target, stderr=subprocess.PIPE, check=False, timeout=120
                )
                if result.returncode:
                    raise RuntimeError("Could not save the storage test image")
            for node in nodes:
                with archive.open("rb") as source:
                    imported = subprocess.run(
                        [
                            "docker",
                            "exec",
                            "-i",
                            node,
                            "ctr",
                            "-n",
                            "k8s.io",
                            "images",
                            "import",
                            "--platform",
                            platform,
                            "-",
                        ],
                        stdin=source,
                        capture_output=True,
                        check=False,
                        timeout=120,
                    )
                    if imported.returncode:
                        raise RuntimeError("Platform-scoped storage test image import failed")
                cached = run(["docker", "exec", node, "ctr", "-n", "k8s.io", "images", "ls", "-q"]).stdout.splitlines()
                if "docker.io/" + image not in cached:
                    raise RuntimeError("The storage test image is not present in the node cache")
        finally:
            archive.unlink(missing_ok=True)
