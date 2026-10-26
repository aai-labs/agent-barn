"""One shared executable and instructions for both existing Agent runtimes."""

from pathlib import Path

from kubernetes import client

ARTIFACT_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_artifacts.py").read_text()
ARTIFACT_COMMAND = '#!/bin/sh\nexec python3 /app/config/agentbarn_artifacts.py "$@"\n'
ARTIFACT_INSTRUCTIONS = """

## Files and download links

File delivery is part of your job, not something the user needs to configure.
When a user asks you to create, export, prepare, attach, share or return a file
(for example a CSV, spreadsheet, report, document, image or archive), create the
actual file in your workspace and publish the finished deliverable automatically.
Do not wait for the user to mention artifacts, storage or the CLI. For example,
"Create a CSV with three sample products" means create the CSV and provide a
working download link, not just CSV text, a local path or instructions for saving it.
Do not ask the user to run an upload command or add a separate upload confirmation
for a file they already asked you to deliver; still follow configured tool approvals.
Respect an explicit request to keep a file local. Do not publish scratch/intermediate files,
credentials or unrelated workspace files. If the user wants an explanation or a code
snippet rather than a file, answer normally; do not turn every reply into an attachment.
Only claim a requested format if you actually created that format.

Use `/usr/local/bin/agentbarn-artifacts upload <local-workspace-file>` through your
normal terminal tool to publish actual file bytes. The command returns the immutable
artifact identity, SHA-256 checksum and a signed download URL. Only claim a file is
published after this succeeds. Use `agentbarn-artifacts list`, `link <artifact-id>`
and `retrieve <artifact-id> <new-local-path>` to find files, renew a link and retrieve
verified bytes. For a previously published file, obtain a fresh link rather than
uploading identical bytes again. Workspace paths and text summaries are not published files.
Give the user a concise Markdown download link, such as `[Download products.csv](URL)`,
with the actual URL returned by the tool, unchanged. Do not expose CLI commands,
internal storage addresses, IDs or checksums in ordinary replies unless requested.
Keep exact IDs/checksums for workflow handoffs and later file operations.
Links expire after 15 minutes by default; mention that briefly when delivering a file.
Anyone holding a link can download until expiry. Share links only through your existing native messaging tools under your
configured approval and messaging policy. Link creation does not send a message.
If file creation or upload fails, do not invent a link or claim delivery succeeded.
If storage is unavailable, report that honestly and continue text-only work; offer
copyable text or a summary when useful, without pretending it is a downloadable file.
Workflow steps must include the current --attempt-id supplied
in their step prompt when uploading. The completion capability is never a file-tool argument. Preserve exact artifact IDs/checksums for
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
