"""Keep the Agent's Tasks current without relying on the prompt alone.

Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
command stays the one client of the Task routes. Each turn starts with the Agent's open
Tasks. A turn that does real work without touching a Task (three or more tool calls, or
any file it writes) is reminded inside the turn through the tool result the model reads
next; a turn that wrote files is also held back once before it finishes (`pre_verify`).
If it still ends without a Task, the next turn carries a reminder. The plugin never
records a Task itself.
"""

import json
import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_TOOL = "agentbarn_task"
_STATUSES = ["open", "in_progress", "done", "failed"]
_WORK_THRESHOLD = 3
# The startup checklist (boot-run.py) runs in this session; it is not a request to keep a Task for.
_BOOT_SESSION_ID = "agentbarn-boot"
# Hermes's own file-writing tools. A turn that produces a file is worth a Task however short it is.
_FILE_TOOLS = {"write_file", "patch"}
_OPEN_TASKS_TTL_SECONDS = 60
_OPEN_TASKS_SHOWN = 10
_COMMAND_TIMEOUT_SECONDS = 150

_IN_TURN_REMINDER = (
    "[Agent Barn] This request has taken several steps and has no Task yet. Record it with the "
    "agentbarn_task tool: create a Task, keep its status current and add notes as you go. The files you "
    "produce are attached to it for you."
)
_BEFORE_FINISHING_REMINDER = (
    "Before you finish: this turn produced files but recorded no Task. Record it now with the "
    "agentbarn_task tool (create the Task, add a note on what was done, set its status), then give your "
    "answer. The files you produced are attached to it for you."
)
# Next to every request, as on OpenClaw: so the Task exists from the start of the work, not the end.
# About 45 tokens per request.
_REQUEST_LINE = (
    "If this request needs tools or produces files, create a Task with agentbarn_task as in_progress before "
    "you start and keep it current. Don't mention Tasks in your reply unless the user asks."
)
_QUIET = " Record it quietly and answer the user's message as normal; do not report the bookkeeping."
_NEXT_TURN_REMINDER = (
    "Your previous turn did work without recording it as a Task. If it was more than a quick answer, "
    "record it now with the agentbarn_task tool: create the Task, add a note on what was done, attach "
    "any files and set its status."
)

_SCHEMA = {
    "name": _TOOL,
    "description": (
        "Record your own work as Tasks the people you work for can follow. Create a Task for any request "
        "that takes more than a quick answer, keep its status current, add notes as you go and attach the "
        "files you produce. Check `list` before creating, to continue a Task that already covers the request."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "status", "note", "attach", "remove_file", "list", "show"],
            },
            "task_id": {"type": "string", "description": "The Task's id, for status, note, attach and show."},
            "title": {"type": "string", "description": "A short title, for create."},
            "description": {"type": "string", "description": "What was asked, for create."},
            "status": {
                "type": "string",
                "enum": _STATUSES,
                "description": "The new status, a list filter, or the starting status for create.",
            },
            "body": {"type": "string", "description": "The note, for note."},
            "path": {"type": "string", "description": "The file to attach, absolute or relative to your workspace."},
            "name": {"type": "string", "description": "The file's name as shown on the Task, for attach."},
            "content_type": {"type": "string", "description": "A bare type/subtype, for attach."},
            "file_id": {"type": "string", "description": "The file's id from show, for remove_file."},
        },
        "required": ["action"],
    },
}

_lock = threading.Lock()
# (session_id, turn_id) -> what the turn did: tool call ids, files written and attached, Tasks touched
_turns: dict[tuple[str, str], dict] = {}
# session_id -> its current turn_id; pre_verify is not told which turn it is judging.
_current_turn: dict[str, str] = {}
# session_id -> the reminder its next turn starts with
_next_turn_reminders: dict[str, str] = {}
_open_tasks_cache: dict = {"at": 0.0, "lines": None}


def _command() -> str:
    return os.environ.get("AGENTBARN_TASK_COMMAND") or "/usr/local/bin/agentbarn-task"


def _workspace() -> str:
    return os.environ.get("TERMINAL_CWD") or os.getcwd()


def _run(argv: list[str], stdin: str = "") -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [_command(), *argv],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            cwd=_workspace(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Agent Barn Tasks are unavailable right now, so the change was not confirmed."
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "The Task command failed, so the change was not confirmed."
    return True, completed.stdout.strip()


def _argv(args: dict) -> tuple[list[str], str] | str:
    """The command line for one tool call, or what is missing from it."""
    action = args.get("action")
    task_id = args.get("task_id") or ""
    if action == "create":
        if not args.get("title"):
            return "create needs a title."
        argv = ["create", "--title", args["title"]]
        if args.get("description"):
            argv += ["--description", args["description"]]
        if args.get("status") in _STATUSES:
            argv += ["--status", args["status"]]
        return argv, ""
    if action == "list":
        return (["list", "--status", args["status"]] if args.get("status") else ["list"]), ""
    if not task_id:
        return f"{action} needs a task_id."
    if action == "show":
        return ["show", task_id], ""
    if action == "remove_file":
        if not args.get("file_id"):
            return "remove_file needs a file_id, from the Task's files in show."
        return ["remove-file", task_id, args["file_id"]], ""
    if action == "status":
        if args.get("status") not in _STATUSES:
            return "status needs one of: " + ", ".join(_STATUSES) + "."
        return ["status", task_id, args["status"]], ""
    if action == "note":
        if not args.get("body"):
            return "note needs a body."
        return ["note", task_id], args["body"]
    if action == "attach":
        if not args.get("path"):
            return "attach needs a path."
        argv = ["attach", task_id, args["path"]]
        if args.get("name"):
            argv += ["--name", args["name"]]
        if args.get("content_type"):
            argv += ["--content-type", args["content_type"]]
        return argv, ""
    return "action must be one of: create, status, note, attach, remove_file, list, show."


def _handle_tool(args: dict, **_) -> str:
    built = _argv(args if isinstance(args, dict) else {})
    if isinstance(built, str):
        return json.dumps({"error": built})
    argv, stdin = built
    ok, output = _run(argv, stdin)
    if argv[0] not in {"list", "show"}:
        with _lock:
            _open_tasks_cache["lines"] = None
    if not ok:
        return json.dumps({"error": output})
    try:
        return json.dumps(json.loads(output))
    except ValueError:
        return json.dumps({"result": output})


def _touches_tasks(tool_name: str, args) -> bool:
    if tool_name == _TOOL:
        return True
    command = args.get("command") if isinstance(args, dict) else None
    return isinstance(command, str) and "agentbarn-task" in command


def _attached_names(tool_name: str, args) -> set[str]:
    """File names a call attached to a Task, through the tool or the command."""
    if not isinstance(args, dict):
        return set()
    if tool_name == _TOOL:
        path = args.get("path") if args.get("action") == "attach" else None
        return {os.path.basename(path)} if isinstance(path, str) and path else set()
    command = args.get("command")
    if isinstance(command, str) and "agentbarn-task attach" in command:
        return {os.path.basename(token) for token in command.split() if token}
    return set()


def _task_id(tool_name: str, args, result) -> str | None:
    """The Task a call of the Task tool acted on: its task_id, or the id a create returned."""
    if tool_name != _TOOL or not isinstance(args, dict):
        return None
    if isinstance(args.get("task_id"), str) and args["task_id"]:
        return args["task_id"]
    if args.get("action") == "create" and isinstance(result, str):
        try:
            created = json.loads(result)
        except ValueError:
            return None
        if isinstance(created, dict) and isinstance(created.get("id"), str):
            return created["id"]
    return None


def _track(
    tool_name: str = "", args=None, session_id: str = "", turn_id: str = "", tool_call_id: str = "", result=None
) -> dict:
    """Count one tool call in its turn. Safe to call twice for the same call."""
    _current_turn[session_id] = turn_id
    turn = _turns.setdefault(
        (session_id, turn_id),
        {
            "work": set(),
            "wrote_files": False,
            "written": {},
            "recorded": False,
            "task_ids": set(),
            "attached": set(),
            "reminded": False,
            "held": False,
        },
    )
    if _touches_tasks(tool_name, args):
        turn["recorded"] = True
        turn["attached"] |= _attached_names(tool_name, args)
        task_id = _task_id(tool_name, args, result)
        if task_id:
            turn["task_ids"].add(task_id)
    else:
        if tool_call_id:
            turn["work"].add(tool_call_id)
        if tool_name in _FILE_TOOLS:
            turn["wrote_files"] = True
            path = args.get("path") if isinstance(args, dict) else None
            if isinstance(path, str) and path:
                full = os.path.normpath(os.path.join(_workspace(), path))
                turn["written"][os.path.basename(full)] = full
    return turn


def _unrecorded_work(turn: dict | None) -> bool:
    return bool(turn) and not turn["recorded"] and (turn["wrote_files"] or len(turn["work"]) >= _WORK_THRESHOLD)


def _unattached(turn: dict) -> dict[str, str]:
    return {name: path for name, path in turn["written"].items() if name not in turn["attached"]}


def _attach_reminder(names: list[str]) -> str:
    return (
        f"These files you produced are not on a Task yet: {', '.join(names)}. Attach the ones that are part of "
        "the result with the agentbarn_task tool (action attach)."
    )


def _attach_automatically(turn: dict) -> list[str]:
    """Attach the turn's files to the one Task it touched. Returns the names it could not attach."""
    unattached = _unattached(turn)
    if len(turn["task_ids"]) != 1:
        return sorted(unattached)
    (task_id,) = turn["task_ids"]
    limit = os.environ.get("TASK_FILE_MAX_BYTES", "")
    failed = []
    for name, path in sorted(unattached.items()):
        if not os.path.isfile(path):
            continue
        if limit.isdigit() and os.path.getsize(path) > int(limit):
            continue
        ok, _ = _run(["attach", task_id, path])
        if not ok:
            failed.append(name)
    return failed


def _on_post_tool_call(tool_name="", args=None, result=None, session_id="", turn_id="", tool_call_id="", **_):
    if session_id == _BOOT_SESSION_ID:
        return
    with _lock:
        _track(tool_name, args, session_id, turn_id, tool_call_id, result)


def _on_transform_tool_result(tool_name="", args=None, result=None, session_id="", turn_id="", tool_call_id="", **_):
    if session_id == _BOOT_SESSION_ID:
        return None
    with _lock:
        turn = _track(tool_name, args, session_id, turn_id, tool_call_id, result)
        if turn["reminded"] or not _unrecorded_work(turn):
            return None
        turn["reminded"] = True
    return f"{result if isinstance(result, str) else json.dumps(result)}\n\n{_IN_TURN_REMINDER}"


def _on_session_end(session_id="", turn_id="", completed=False, **_):
    """Hermes fires this at the end of every turn, despite its name.

    A turn's files go to the one Task it touched without asking the model; the Agent can
    remove any that are not part of the result. Only what could not be attached is named
    on the next turn.
    """
    with _lock:
        turn = _turns.pop((session_id, turn_id), None)
        if _current_turn.get(session_id) == turn_id:
            del _current_turn[session_id]
    if turn is None or not completed:
        return
    if _unrecorded_work(turn):
        reminder = _NEXT_TURN_REMINDER
    else:
        failed = _attach_automatically(turn) if turn["recorded"] else []
        if not failed:
            return
        reminder = _attach_reminder(failed)
    with _lock:
        _next_turn_reminders[session_id] = reminder + _QUIET


def _on_pre_verify(session_id="", **_):
    """Hold back once a turn that wrote files but recorded no Task. Hermes calls this only after file edits."""
    if session_id == _BOOT_SESSION_ID:
        return None
    with _lock:
        turn = _turns.get((session_id, _current_turn.get(session_id, "")))
        if turn is None or turn["held"] or not _unrecorded_work(turn):
            return None
        turn["held"] = True
    return {"action": "continue", "message": _BEFORE_FINISHING_REMINDER}


def _open_task_lines() -> list[str] | None:
    with _lock:
        cached = _open_tasks_cache["lines"]
        if cached is not None and time.monotonic() - _open_tasks_cache["at"] < _OPEN_TASKS_TTL_SECONDS:
            return cached
    lines = []
    for task_status in ("in_progress", "open"):
        ok, output = _run(["list", "--status", task_status])
        if not ok:
            return None
        try:
            items = json.loads(output)["items"]
        except (ValueError, KeyError, TypeError):
            return None
        for task in items:
            title = str(task.get("title", ""))[:120]
            lines.append(f"- {task.get('id')} [{task.get('status')}] {title}")
    lines = lines[:_OPEN_TASKS_SHOWN]
    with _lock:
        _open_tasks_cache.update({"at": time.monotonic(), "lines": lines})
    return lines


def _on_pre_llm_call(session_id="", **_):
    if session_id == _BOOT_SESSION_ID:
        return None
    parts = ["[Agent Barn] " + _REQUEST_LINE]
    lines = _open_task_lines()
    if lines:
        parts.append(
            "[Agent Barn] Your open Tasks:\n"
            + "\n".join(lines)
            + "\nKeep their status current with the agentbarn_task tool, and mark a Task done or failed when "
            "its work ends."
        )
    with _lock:
        reminder = _next_turn_reminders.pop(session_id, None)
    if reminder:
        parts.append("[Agent Barn] " + reminder)
    return {"context": "\n\n".join(parts)} if parts else None


def register(ctx):
    if not (os.environ.get("AGENT_ID") and os.environ.get("INGEST_URL") and os.environ.get("INGEST_API_KEY")):
        return
    ctx.register_tool(
        name=_TOOL,
        toolset="agentbarn",
        schema=_SCHEMA,
        handler=_handle_tool,
        description=_SCHEMA["description"],
        emoji="📋",
    )
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("pre_verify", _on_pre_verify)
