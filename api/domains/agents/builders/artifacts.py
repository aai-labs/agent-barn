"""One shared executable and instructions for both existing Agent runtimes."""

from pathlib import Path

from kubernetes import client

ARTIFACT_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_artifacts.py").read_text()
ARTIFACT_COMMAND = '#!/bin/sh\nexec python3 /app/config/agentbarn_artifacts.py "$@"\n'
ARTIFACT_INSTRUCTIONS = """

## Files and download links

When someone asks for a file (CSV, spreadsheet, report, document, image, archive), create it in your
workspace and publish it with `/usr/local/bin/agentbarn-artifacts upload <file>`. Reply with
`[Download <name>](<url>)`, the returned URL unchanged, and say the link expires in 15 minutes. For a
file already published, get a fresh link with `agentbarn-artifacts link <id>` instead of uploading it
again (`list` and `retrieve <id> <path>` find and fetch earlier files). Claim delivery only after the
upload succeeds; if it fails, say so and offer the content as text, never a workspace path (people
can't open it) or a link of your own. Publish only finished deliverables, never scratch files or
credentials; keep a file local when asked; don't show commands, IDs or checksums unless asked. In a
workflow step, pass the step's `--attempt-id` when uploading.
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
