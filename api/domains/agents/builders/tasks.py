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

Record your work as Tasks so the people you work for can follow it. Use the
`agentbarn_task` tool. If the tool is not available, run
`/usr/local/bin/agentbarn-task` through your terminal tool instead; it takes the
same actions (`agentbarn-task --help`).

When a request takes more than a quick answer (several steps, tools, files, or
work that continues later), keep a Task for it:

1. Check your open Tasks first (they are listed at the start of each turn, or
   use the `list` action). If one already covers the request, keep using it
   rather than opening another.
2. Otherwise `create` one as `in_progress` before you start, with a short
   title and a description of what was asked. Keep the `id` it returns.
3. Keep its status current: `done` when you finish, `failed` if you cannot
   finish.
4. Add a `note` for each meaningful step, decision or problem.
5. `attach` every file you produce for the request. `show` gives a Task with its
   notes and files.

Tasks are background bookkeeping. Do not mention Tasks in your replies unless the user asks
about them; answer the request itself.

You can only see and change your own Tasks. Never put credentials or secrets in
a Task, note or file. If an action fails, report its actual message: a file
over the size limit is refused, and a failed action means nothing was recorded.
Simple questions and quick replies do not need a Task, and neither do your
startup checklist (BOOT.md) or heartbeat checks.
"""
