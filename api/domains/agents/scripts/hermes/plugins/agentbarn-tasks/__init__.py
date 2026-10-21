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
# Hermes's own file-writing tools. A turn that produces a file is worth a Task however short it is.
_FILE_TOOLS = {"write_file", "patch"}
_OPEN_TASKS_TTL_SECONDS = 60
_OPEN_TASKS_SHOWN = 10
_COMMAND_TIMEOUT_SECONDS = 150

_IN_TURN_REMINDER = (
    "[Agent Barn] This request has taken several steps and has no Task yet. Record it with the "
    "agentbarn_task tool: create a Task, keep its status current, add notes as you go and attach "
    "the files you produce."
)
_BEFORE_FINISHING_REMINDER = (
    "Before you finish: this turn produced files but recorded no Task. Record it now with the "
    "agentbarn_task tool (create the Task, add a note on what was done, attach the files you produced, "
    "set its status), then give your answer."
)
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
            "action": {"type": "string", "enum": ["create", "status", "note", "attach", "list", "show"]},
            "task_id": {"type": "string", "description": "The Task's id, for status, note, attach and show."},
            "title": {"type": "string", "description": "A short title, for create."},
            "description": {"type": "string", "description": "What was asked, for create."},
            "status": {"type": "string", "enum": _STATUSES, "description": "The new status, or a list filter."},
            "body": {"type": "string", "description": "The note, for note."},
            "path": {"type": "string", "description": "The file to attach, absolute or relative to your workspace."},
            "name": {"type": "string", "description": "The file's name as shown on the Task, for attach."},
            "content_type": {"type": "string", "description": "A bare type/subtype, for attach."},
        },
        "required": ["action"],
    },
}

_lock = threading.Lock()
# (session_id, turn_id) -> {"work": set of tool call ids, "wrote_files", "recorded", "reminded", "held"}
_turns: dict[tuple[str, str], dict] = {}
# session_id -> its current turn_id; pre_verify is not told which turn it is judging.
_current_turn: dict[str, str] = {}
_remind_next_turn: set[str] = set()
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
        return argv, ""
    if action == "list":
        return (["list", "--status", args["status"]] if args.get("status") else ["list"]), ""
    if not task_id:
        return f"{action} needs a task_id."
    if action == "show":
        return ["show", task_id], ""
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
    return "action must be one of: create, status, note, attach, list, show."


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


def _track(tool_name: str = "", args=None, session_id: str = "", turn_id: str = "", tool_call_id: str = "") -> dict:
    """Count one tool call in its turn. Safe to call twice for the same call."""
    _current_turn[session_id] = turn_id
    turn = _turns.setdefault(
        (session_id, turn_id),
        {"work": set(), "wrote_files": False, "recorded": False, "reminded": False, "held": False},
    )
    if _touches_tasks(tool_name, args):
        turn["recorded"] = True
    else:
        if tool_call_id:
            turn["work"].add(tool_call_id)
        if tool_name in _FILE_TOOLS:
            turn["wrote_files"] = True
    return turn


def _unrecorded_work(turn: dict | None) -> bool:
    return bool(turn) and not turn["recorded"] and (turn["wrote_files"] or len(turn["work"]) >= _WORK_THRESHOLD)


def _on_post_tool_call(tool_name="", args=None, session_id="", turn_id="", tool_call_id="", **_):
    with _lock:
        _track(tool_name, args, session_id, turn_id, tool_call_id)


def _on_transform_tool_result(tool_name="", args=None, result=None, session_id="", turn_id="", tool_call_id="", **_):
    with _lock:
        turn = _track(tool_name, args, session_id, turn_id, tool_call_id)
        if turn["reminded"] or not _unrecorded_work(turn):
            return None
        turn["reminded"] = True
    return f"{result if isinstance(result, str) else json.dumps(result)}\n\n{_IN_TURN_REMINDER}"


def _on_session_end(session_id="", turn_id="", completed=False, **_):
    """Hermes fires this at the end of every turn, despite its name."""
    with _lock:
        turn = _turns.pop((session_id, turn_id), None)
        if _current_turn.get(session_id) == turn_id:
            del _current_turn[session_id]
        if completed and _unrecorded_work(turn):
            _remind_next_turn.add(session_id)


def _on_pre_verify(session_id="", **_):
    """Hold back once a turn that wrote files but recorded no Task. Hermes calls this only after file edits."""
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
    parts = []
    lines = _open_task_lines()
    if lines:
        parts.append(
            "[Agent Barn] Your open Tasks:\n"
            + "\n".join(lines)
            + "\nKeep their status current with the agentbarn_task tool, and mark a Task done or failed when "
            "its work ends."
        )
    with _lock:
        if session_id in _remind_next_turn:
            _remind_next_turn.discard(session_id)
            parts.append("[Agent Barn] " + _NEXT_TURN_REMINDER)
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
