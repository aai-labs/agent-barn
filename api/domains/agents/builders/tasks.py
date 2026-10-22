"""The in-pod Task command, installed for every Agent on both runtimes."""

from pathlib import Path

from kubernetes import client

TASK_COMMAND = '#!/bin/sh\nexec python3 /app/config/agentbarn_task.py "$@"\n'
TASK_COMMAND_PATH = "/usr/local/bin/agentbarn-task"


def task_command_mount() -> client.V1VolumeMount:
    return client.V1VolumeMount(
        name="task-command", mount_path=TASK_COMMAND_PATH, sub_path="agentbarn-task", read_only=True
    )


def task_command_volume(config_name: str) -> client.V1Volume:
    return client.V1Volume(
        name="task-command",
        config_map=client.V1ConfigMapVolumeSource(
            name=config_name, items=[client.V1KeyToPath(key="agentbarn-task", path="agentbarn-task", mode=0o555)]
        ),
    )


TASK_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_task.py").read_text()
TASK_TOOL_INSTRUCTIONS = """

## Tasks

Record work that uses tools or produces files as a Task, so the people you work
for can follow it. Use the `agentbarn_task` tool. If the tool is not available,
run `/usr/local/bin/agentbarn-task` through your terminal tool instead
(`agentbarn-task --help`), and then set the status and attach files yourself.

- Before you start, check the Tasks listed at the start of each turn (your open
  ones and the latest finished ones). If the request continues one, keep using
  it (set a finished one back to `in_progress`); otherwise `create` one with a
  short title.
- The Task you worked on is marked `done` when your turn ends, and the files you
  wrote are attached to it. `show` lists them; remove any that are not part of
  the result with `remove_file`.
- If the work failed, set `failed` with a `body` saying why. If you stop to wait
  for the user, set `open`; it stays listed for you to continue.
- Add a `body` (a note) only for a decision or problem worth knowing later.
- Quick answers, small talk, your startup checklist (BOOT.md) and heartbeat
  checks do not need a Task.

Tasks are background bookkeeping. Do not mention Tasks in your replies unless the user asks
about them. You can only see your own Tasks; never put credentials or secrets in
them. If an action fails, report its message: a failed action recorded nothing.
"""
