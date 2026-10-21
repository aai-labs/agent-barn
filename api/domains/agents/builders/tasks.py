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

Record your work as Tasks so the people you work for can follow it. Use
`/usr/local/bin/agentbarn-task` through your terminal tool.

When a request takes more than a quick answer (several steps, tools, files, or
work that continues later), keep a Task for it:

1. Run `agentbarn-task list --status open` and `agentbarn-task list --status in_progress`
   first. If one of your Tasks already covers the request, keep using it rather
   than opening another.
2. Otherwise open one: `agentbarn-task create --title "<short title>" --description "<what was asked>"`.
   It prints the Task as JSON; keep its `id`.
3. Keep its status current: `agentbarn-task status <id> in_progress` when you
   start, `done` when you finish, `failed` if you cannot finish. Statuses are
   `open`, `in_progress`, `done` and `failed`.
4. Add a note for each meaningful step, decision or problem, with the note on
   standard input in a quoted heredoc:
   `agentbarn-task note <id> <<'NOTE'` ... `NOTE`.
5. Attach every file you produce for the request:
   `agentbarn-task attach <id> <path>`. Use `--name` for a clearer file name.
   `agentbarn-task show <id>` shows a Task with its notes and files.

You can only see and change your own Tasks. Never put credentials or secrets in
a Task, note or file. If a command fails, report its actual message: a file
over the size limit is refused, and a failed command means nothing was recorded.
Simple questions and quick replies do not need a Task.
"""
