"""Keep the Agent's Tasks current without relying on the prompt alone.

Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
command stays the one client of the Task routes. Each turn starts with the Agent's open
Tasks. A turn that does real work without touching a Task (three or more tool calls, or
any file it writes) is reminded inside the turn through the tool result the model reads
next; a turn that wrote files is also held back once before it finishes (`pre_verify`).
If it still ends without a Task, the plugin records one itself, named after the request,
with origin `automatic`. It also does the bookkeeping that would otherwise cost the model
a call each: when a turn ends, the files it wrote go to the Task it worked on and a Task
it left in progress is marked done. Runs with a parent session (Hermes's background
review, subagents) are left alone: they are not the user's request.
"""

import json
import logging
import os
import re
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
# Recently finished Tasks are listed too, so a follow-up reopens its Task rather than starting another.
_DONE_TASKS_SHOWN = 3
_AUTOMATIC_TITLE_CHARS = 120
_AUTOMATIC_DESCRIPTION_CHARS = 2000
_COMMAND_TIMEOUT_SECONDS = 150
# A short message made only of these words is small talk ("Thanks!", "That's all for now"): it gets
# no request line. Approvals ("ok", "yes", "go ahead") are left out on purpose: they can start work.
_SMALL_TALK_MAX_WORDS = 8
_SMALL_TALK_WORDS = frozenset(
    [
        "hi",
        "hey",
        "hello",
        "thanks",
        "thank",
        "you",
        "thx",
        "ty",
        "cheers",
        "great",
        "nice",
        "cool",
        "awesome",
        "perfect",
        "lovely",
        "good",
        "sounds",
        "that",
        "thats",
        "is",
        "was",
        "all",
        "for",
        "now",
        "bye",
        "goodbye",
        "see",
        "ya",
        "later",
        "much",
        "so",
        "very",
        "appreciate",
        "appreciated",
        "it",
        "got",
        "morning",
        "afternoon",
        "evening",
        "night",
        "have",
        "a",
        "day",
        "weekend",
        "wow",
        "haha",
        "lol",
    ]
)

_IN_TURN_REMINDER = (
    "[Agent Barn] This request has taken several steps and has no Task yet. Create one with the "
    "agentbarn_task tool. Your files are attached and the Task is marked done when the turn ends."
)
_BEFORE_FINISHING_REMINDER = (
    "Before you finish: this turn produced files but recorded no Task. Create one with the agentbarn_task "
    "tool (a body says what was done), then give your answer. Your files are attached to it for you."
)
# Next to every request but small talk, as on OpenClaw: so the Task exists from the start of the
# work, not the end. About 40 tokens.
_REQUEST_LINE = (
    "If this request needs tools or produces files, create a Task with agentbarn_task before you start, "
    "or continue an open one. Don't mention Tasks in your reply unless the user asks."
)
_QUIET = " Record it quietly and answer the user's message as normal; do not report the bookkeeping."

_SCHEMA = {
    "name": _TOOL,
    "description": (
        "Record work that uses tools or produces files as a Task the people you work for can follow. "
        "`create` one before you start (it starts in_progress); when your turn ends, the files you wrote are "
        "attached and a Task still in_progress is marked done. Set `failed` (with a body saying why) or "
        "`open` (waiting on the user) yourself."
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
                "description": "The new status, a list filter, or the starting status for create (in_progress).",
            },
            "body": {"type": "string", "description": "The note, for note; or one to add with create or status."},
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
# session_id -> the user's latest request, the title of a Task recorded automatically
_requests: dict[str, str] = {}
# (session_id, turn_id) of runs with a parent session: the background review and subagents
_side_runs: set[tuple[str, str]] = set()


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
        argv += ["--status", args["status"] if args.get("status") in _STATUSES else "in_progress"]
        if args.get("body"):
            argv += ["--note", args["body"]]
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
        argv = ["status", task_id, args["status"]]
        if args.get("body"):
            argv += ["--note", args["body"]]
        return argv, ""
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
        return [*argv, "--replace"], ""
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


def _status_set(tool_name: str, args) -> str | None:
    """The status a call of the Task tool left its Task in, if it set one."""
    if tool_name != _TOOL or not isinstance(args, dict):
        return None
    if args.get("action") == "create":
        return args["status"] if args.get("status") in _STATUSES else "in_progress"
    if args.get("action") == "status" and args.get("status") in _STATUSES:
        return args["status"]
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
            # task_id -> the last status the Agent set this turn
            "statuses": {},
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
            status = _status_set(tool_name, args)
            if status:
                turn["statuses"][task_id] = status
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
        ok, _ = _run(["attach", task_id, path, "--replace"])
        if not ok:
            failed.append(name)
    return failed


def _close_in_progress(turn: dict) -> None:
    """Mark done each Task the Agent left in_progress this turn; a status it chose itself stays."""
    closed = False
    for task_id, status in sorted(turn["statuses"].items()):
        if status == "in_progress":
            _run(["status", task_id, "done"])
            closed = True
    if closed:
        with _lock:
            _open_tasks_cache["lines"] = None


def _record_automatically(session_id: str, turn: dict) -> list[str]:
    """Record a Task for work the Agent left unrecorded. Returns the files it could not attach."""
    with _lock:
        request = " ".join(_requests.get(session_id, "").split())
    title = request or "Work recorded automatically"
    if len(title) > _AUTOMATIC_TITLE_CHARS:
        title = title[: _AUTOMATIC_TITLE_CHARS - 1].rstrip() + "…"
    argv = ["create", "--title", title, "--status", "done", "--origin", "automatic"]
    if request:
        argv += ["--description", request[:_AUTOMATIC_DESCRIPTION_CHARS]]
    ok, output = _run(argv)
    with _lock:
        _open_tasks_cache["lines"] = None
    try:
        task_id = json.loads(output).get("id") if ok else None
    except (ValueError, AttributeError):
        task_id = None
    if not isinstance(task_id, str):
        return sorted(_unattached(turn))
    turn["task_ids"] = {task_id}
    return _attach_automatically(turn)


def _side_run(session_id: str, turn_id: str) -> bool:
    with _lock:
        return session_id == _BOOT_SESSION_ID or (session_id, turn_id) in _side_runs


def _on_post_tool_call(tool_name="", args=None, result=None, session_id="", turn_id="", tool_call_id="", **_):
    if _side_run(session_id, turn_id):
        return
    with _lock:
        _track(tool_name, args, session_id, turn_id, tool_call_id, result)


def _on_transform_tool_result(tool_name="", args=None, result=None, session_id="", turn_id="", tool_call_id="", **_):
    if _side_run(session_id, turn_id):
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
    remove any that are not part of the result. Work the Agent did not record at all is
    recorded automatically. Only what could not be attached is named on the next turn.
    """
    with _lock:
        _side_runs.discard((session_id, turn_id))
        turn = _turns.pop((session_id, turn_id), None)
        if _current_turn.get(session_id) == turn_id:
            del _current_turn[session_id]
    if turn is None or not completed:
        return
    if _unrecorded_work(turn):
        failed = _record_automatically(session_id, turn)
    elif turn["recorded"]:
        failed = _attach_automatically(turn)
        _close_in_progress(turn)
    else:
        return
    if failed:
        with _lock:
            _next_turn_reminders[session_id] = _attach_reminder(failed) + _QUIET


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
    for task_status in ("in_progress", "open", "done"):
        ok, output = _run(["list", "--status", task_status])
        if not ok:
            return None
        try:
            items = json.loads(output)["items"]
        except (ValueError, KeyError, TypeError):
            return None
        for task in items[: _DONE_TASKS_SHOWN if task_status == "done" else _OPEN_TASKS_SHOWN]:
            title = str(task.get("title", ""))[:120]
            lines.append(f"- {task.get('id')} [{task.get('status')}] {title}")
    with _lock:
        _open_tasks_cache.update({"at": time.monotonic(), "lines": lines})
    return lines


def _small_talk(message) -> bool:
    words = re.findall(r"[a-z]+", message.lower().replace("'", "")) if isinstance(message, str) else []
    return 0 < len(words) <= _SMALL_TALK_MAX_WORDS and all(word in _SMALL_TALK_WORDS for word in words)


def _on_pre_llm_call(session_id="", turn_id="", user_message="", parent_session_id="", **_):
    if session_id == _BOOT_SESSION_ID:
        return None
    if parent_session_id:
        with _lock:
            _side_runs.add((session_id, turn_id))
        return None
    if isinstance(user_message, str):
        with _lock:
            _requests[session_id] = user_message
    parts = [] if _small_talk(user_message) else ["[Agent Barn] " + _REQUEST_LINE]
    lines = _open_task_lines()
    if lines:
        parts.append(
            "[Agent Barn] Your open and latest finished Tasks:\n"
            + "\n".join(lines)
            + "\nIf the request continues one of these, keep using it with the agentbarn_task tool (set a done "
            "one back to in_progress) rather than creating another."
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
