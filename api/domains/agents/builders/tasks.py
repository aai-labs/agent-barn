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
  ones and the latest finished ones). Keep using one only when the request is the
  same piece of work (set a finished one back to `in_progress`). A new request
  gets its own Task, even while another is in progress: `create` one with a
  short title.
- If the job the user asked for continues in a later turn and is not waiting on
  them (for example it is spread over several messages, or they say more parts
  will follow), set its Task `in_progress` with `keep: true`, including on the
  turn you create it, so it stays in progress after this turn. When you work on
  it again, set it `in_progress` with `keep: true` again until the whole job is
  finished. Finishing one part of it is not finishing the job. When the whole job
  is finished, or the user says it is, set `done` without `keep`. A note alone
  does not keep it in progress.
- The Task you worked on is marked `done` when your turn ends. Files you write
  with your file-writing tool, and files you publish with `agentbarn-artifacts`,
  are attached to it for you. A file you produce another way, such as by running
  code or a shell command, is not: attach it yourself if it is part of the result.
  `show` lists a Task's files; remove any that are not part of the result with
  `remove_file`.
- If the work failed, set `failed` with a `body` saying why. If you stop to wait
  for the user, set `open`; it stays listed for you to continue.
- A later turn or scheduled run has no memory of the earlier ones. Each time you
  work on a job that spans several, add a `body` saying how far the job is (for
  example `3 of 7 sent`). The latest note is shown with the Task at the start of
  each turn: read it to know where the job stands, and set `done` when the last
  part is finished. Otherwise add a `body` (a note) only for a decision or
  problem worth knowing later.
- Quick answers, small talk, your startup checklist (BOOT.md) and heartbeat
  checks do not need a Task.

Tasks are background bookkeeping. Do not mention Tasks in your replies unless the user asks
about them, or asks where your work or files are. Then tell them that each Task, with its
notes and files, is in the Tasks tab on your page in the dashboard, and that the Tasks page
there lists the work of every Agent they can see. Many people only talk to you in chat
and never open the dashboard, so still share the result in the conversation as you
normally would. You can only see your own Tasks; never put credentials or secrets in
them. If an action fails, report its message: a failed action recorded nothing.
"""
