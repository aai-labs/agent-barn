"""Exercise the generated Hermes init-container contract against a real image."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from api.domains.agents.builders.hermes import build_hermes_deployment

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")


def run(*args: str, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def main(image: str) -> None:
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, "agent-farm", image)
    pod_spec = deployment.spec.template.spec
    init = pod_spec.init_containers[0]
    data_mount = next(mount for mount in init.volume_mounts if mount.name == "data")
    run_as_user = init.security_context.run_as_user
    volume = run("docker", "volume", "create", capture_output=True).stdout.strip()

    try:
        # Seed through a path absent from the image so Docker doesn't copy the
        # image's /opt/data ownership into an empty volume. This reproduces a
        # root-owned filesystem from a fresh Kubernetes block volume.
        run(
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{volume}:/mnt/fresh-pvc",
            image,
            "sh",
            "-c",
            "touch /mnt/fresh-pvc/.fresh-volume && chown 0:0 /mnt/fresh-pvc /mnt/fresh-pvc/.fresh-volume",
        )
        run(
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{volume}:{data_mount.mount_path}",
            image,
            "sh",
            "-c",
            f'test "$(stat -c %u:%g {data_mount.mount_path})" = "0:0"',
        )

        # Kubernetes `command` replaces the image entrypoint; mirror that
        # behavior while taking every relevant value from the generated spec.
        run(
            "docker",
            "run",
            "--rm",
            "--user",
            str(run_as_user),
            "-v",
            f"{volume}:{data_mount.mount_path}",
            "--entrypoint",
            init.command[0],
            init.image,
            *init.command[1:],
        )

        # Start the image as its default non-root user and perform the writes
        # that originally crashed Hermes, plus a persistent workspace write.
        run(
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume}:{data_mount.mount_path}",
            image,
            "sh",
            "-c",
            'test "$(id -un)" = hermes && '
            'test "$(stat -c %U:%G /opt/data)" = hermes:hermes && '
            'test "$(stat -c %U:%G /opt/data/workspace)" = hermes:hermes && '
            "mkdir -p /opt/data/plugins /opt/data/memories && "
            "touch /opt/data/plugins/.write-test "
            "/opt/data/memories/.write-test /opt/data/workspace/.write-test",
        )
    finally:
        subprocess.run(
            ("docker", "volume", "rm", volume),
            check=False,
            stdout=subprocess.DEVNULL,
        )

    print("Hermes PVC permissions test passed")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: hermes_pvc_permissions_driver.py IMAGE")
    main(sys.argv[1])
