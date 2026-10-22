"""One shared executable and instructions for both existing Agent runtimes."""

from pathlib import Path

from kubernetes import client

ARTIFACT_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_artifacts.py").read_text()
ARTIFACT_COMMAND = '#!/bin/sh\nexec python3 /app/config/agentbarn_artifacts.py "$@"\n'
ARTIFACT_INSTRUCTIONS = """

## Files and download links

Use `/usr/local/bin/agentbarn-artifacts upload <local-workspace-file>` through your
normal terminal tool to publish actual file bytes. The command returns the immutable
artifact identity, SHA-256 checksum and a signed download URL. Only claim a file is
published after this succeeds. Use `agentbarn-artifacts list`, `link <artifact-id>`
and `retrieve <artifact-id> <new-local-path>` to find files, renew a link and retrieve
verified bytes. Workspace paths and text summaries are not published files.
Links expire after 15 minutes by default; anyone holding one can download until
expiry. Share links only through your existing native messaging tools under your
configured approval and messaging policy. Link creation does not send a message.
If storage is unavailable, report that honestly and continue text-only work.
Workflow steps must include the current --attempt-id and --attempt-token supplied
in their step prompt when uploading. Preserve exact artifact IDs/checksums for
handoff; a signed URL is never the artifact's identity.
"""


def artifact_command_mount() -> client.V1VolumeMount:
    return client.V1VolumeMount(
        name="artifact-command",
        mount_path="/usr/local/bin/agentbarn-artifacts",
        sub_path="agentbarn-artifacts",
        read_only=True,
    )


def artifact_command_volume(config_name: str) -> client.V1Volume:
    return client.V1Volume(
        name="artifact-command",
        config_map=client.V1ConfigMapVolumeSource(
            name=config_name,
            items=[client.V1KeyToPath(key="agentbarn-artifacts", path="agentbarn-artifacts", mode=0o555)],
        ),
    )
