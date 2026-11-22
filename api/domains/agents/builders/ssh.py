"""Ephemeral relay state; no SSH material belongs on the Agent's persistent volume."""

import shlex

from kubernetes import client


def attach_ssh_volume(deployment: client.V1Deployment, data_root: str) -> None:
    pod = deployment.spec.template.spec
    pod.volumes.append(
        client.V1Volume(
            name="ssh-relay",
            empty_dir=client.V1EmptyDirVolumeSource(medium="Memory", size_limit="16Mi"),
        )
    )
    mount = client.V1VolumeMount(name="ssh-relay", mount_path="/run/agentbarn-ssh")
    pod.containers[0].volume_mounts.append(mount)
    init = pod.init_containers[0]
    init.volume_mounts.append(mount)
    # Hermes uses sh -c; OpenClaw invokes chown directly. Preserve the original
    # argv before adding shell operations, rather than changing chown's path.
    original = shlex.join([*init.command, *(init.args or [])])
    init.command = [
        "sh",
        "-c",
        f"{original} && chown --reference={shlex.quote(data_root)} /run/agentbarn-ssh && chmod 0700 /run/agentbarn-ssh",
    ]
    init.args = None
