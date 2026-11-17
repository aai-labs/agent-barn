"""Keep the Agent's Tasks current without relying on the prompt alone.

Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
command stays the one client of the Task routes. Each turn starts with the Agent's open
Tasks. A turn that does real work without touching a Task (three or more tool calls, or
any file it writes) is reminded inside the turn through the tool result the model reads
next; a turn that wrote files is also held back once before it finishes (`pre_verify`).
If it still ends without a Task, the plugin records one itself, named after the request,
with origin `automatic`. It also does the bookkeeping that would otherwise cost the model
a call each: when a turn ends, the files it wrote go to the Task it worked on and a Task
it left in progress is marked done, or reopened if the turn did not finish; one it kept
(`keep`, for work that continues in a later turn) stays in progress. Only a Task
call that changed something counts as recording the work: reading the Tasks does not.
Runs with a parent session (Hermes's background review, subagents) are left alone: they
are not the user's request.
"""

import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_TOOL = "agentbarn_task"
_STATUSES = ["open", "in_progress", "done", "failed"]
# A Task the Agent left in_progress with keep: work that continues in a later turn. Only a turn
# that did not complete moves it (to open); otherwise it stays in_progress.
_KEPT = "kept"
_WORK_THRESHOLD = 3
# The startup checklist (boot-run.py) runs in this session; it is not a request to keep a Task for.
_BOOT_SESSION_ID = "agentbarn-boot"
# Hermes's own file-writing tools. A turn that produces a file is worth a Task however short it is.
_FILE_TOOLS = {"write_file", "patch"}
_OPEN_TASKS_TTL_SECONDS = 60
# The Task list is read before every turn, so it gets one short call; a slow or failed
# read leaves the list out until the cache expires rather than holding up each turn.
_LIST_TIMEOUT_SECONDS = 10
_LIST_PAGE_SIZE = 100
_OPEN_TASKS_SHOWN = 10
# Recently finished Tasks are listed too, so a follow-up reopens its Task rather than starting another.
_DONE_TASKS_SHOWN = 3
# An unfinished Task is listed with the start of its latest note, so a later turn or scheduled run,
# which has no memory of earlier ones, sees where the work got to.
_LATEST_NOTE_CHARS = 200
_AUTOMATIC_TITLE_CHARS = 120
_AUTOMATIC_DESCRIPTION_CHARS = 2000
_COMMAND_TIMEOUT_SECONDS = 150
# Hermes's scheduler tool, and the session id of a scheduled run: cron_<job id>_<date>_<time>.
_SCHEDULER_TOOL = "cronjob"
_CRON_SESSION = re.compile(r"^cron_([0-9a-f]{12})_\d{8}_\d{6}")
_INTENT_TIMEOUT_SECONDS = 45
_RUN_NOTE_CHARS = 300
# Sessions remembered at once (requests, reminders, turns); the oldest are forgotten first.
_SESSIONS_KEPT = 500
# Task tool actions and command subcommands that change a Task; reading one is not recording work.
_WRITE_ACTIONS = {"create", "status", "note", "attach", "remove_file"}
# A command run as a command (at the start, or after ; & | ( or a newline, by name or full path),
# not merely mentioned.
_COMMAND_WRITE = re.compile(r"(?:^|[;&|(\n])\s*(?:\S*/)?agentbarn-task\s+(?:create|status|note|attach|remove-file)\b")
# A file the Agent published for the user is part of the result, however it was written.
_ARTIFACT_UPLOAD = re.compile(r"(?:^|[;&|(\n])\s*(?:\S*/)?agentbarn-artifacts\s+upload\s+([^;&|)\n]+)")
_REDACTED = "[redacted]"
# Credentials a user may paste into a request. The automatic Task's title and description
# come from the request, and people across the Organization can read them.
_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL), _REDACTED),
    (re.compile(r"(://[^/\s:@]+:)[^/\s@]+@"), rf"\1{_REDACTED}@"),
    (re.compile(r"(?i)(\bbearer\s+)\S+"), rf"\1{_REDACTED}"),
    # The keyword may sit inside a longer name (DB_PASSWORD=, GITHUB_TOKEN=) or a quoted JSON key.
    (
        re.compile(
            r"(?i)(\w*(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
            r"\w*[\"']?\s*(?:[:=]|\bis\b)\s*[\"']?)[^\s\"',}]+"
        ),
        rf"\1{_REDACTED}",
    ),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), _REDACTED),
    (re.compile(r"\b(?:gh[pousr]_|github_pat_|glpat-|xox[abposr]-)[A-Za-z0-9_-]{10,}"), _REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), _REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), _REDACTED),
]
# Files that hold credentials are never attached automatically: anyone who may read the Agent's
# Tasks could download them. The Agent can still attach one on purpose.
_CREDENTIAL_FILE = re.compile(
    r"(?i)^(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pgpass|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?"
    r"|.*\.(?:pem|key|p12|pfx)|.*credentials.*\.json|service[-_]account.*\.json)$"
)
_OPAQUE_WORD = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
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
    "agentbarn_task tool. Files you write with your file-writing tool are attached and the Task is marked "
    "done when the turn ends; attach any other file that is part of the result yourself."
)
_BEFORE_FINISHING_REMINDER = (
    "Before you finish: this turn produced files but recorded no Task. Create one with the agentbarn_task "
    "tool (a body says what was done), then give your answer. Files you wrote with your file-writing tool "
    "are attached to it for you."
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
        "`create` one before you start (it starts in_progress); when your turn ends, files you wrote with your "
        "file-writing tool or published are attached and a Task still in_progress is marked done. If the work "
        "continues in a later turn and is not waiting on the user, set it in_progress with keep: true so it stays "
        "in progress. Attach any other file that is part of the result yourself. Set `failed` (with a body saying "
        "why), `open` (waiting on the user) or `done` yourself."
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
            "keep": {
                "type": "boolean",
                "description": (
                    "With create, or status in_progress: keep the Task in progress after this turn, because the "
                    "job continues in a later turn (more parts or messages to come). Without it the Task is "
                    "marked done when the turn ends."
                ),
            },
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
# The Task lines shown each turn, and when they were read (None: read again)
_task_list_cache: dict = {"at": None, "lines": []}
# session_id -> the user's latest request, the title of a Task recorded automatically
_requests: dict[str, str] = {}
# (session_id, turn_id) of runs with a parent session: the background review and subagents
_side_runs: dict[tuple[str, str], bool] = {}
# (session_id, turn_id) -> the Agent's final reply, noted on a scheduled run's Task
_replies: dict[tuple[str, str], str] = {}
# Scheduled runs already noted on their Task; Hermes can report the end of one run more than once.
_noted_runs: dict[str, bool] = {}


def _remember(mapping: dict, key, value) -> None:
    """Store a value as the newest entry, forgetting the oldest past _SESSIONS_KEPT. Hold _lock."""
    mapping.pop(key, None)
    mapping[key] = value
    while len(mapping) > _SESSIONS_KEPT:
        del mapping[next(iter(mapping))]


def _forget_task_list() -> None:
    with _lock:
        _task_list_cache["at"] = None


def _redacted(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return _OPAQUE_WORD.sub(_opaque, text)


def _opaque(match: re.Match) -> str:
    """A long word that reads like a key: mixed case with digits, or a long hex string (not a UUID)."""
    word = match.group(0)
    mixed = re.search(r"[a-z]", word) and re.search(r"[A-Z]", word) and re.search(r"\d", word)
    return _REDACTED if mixed or re.fullmatch(r"[0-9a-fA-F]{32,}", word) else word


def _command() -> str:
    return os.environ.get("AGENTBARN_TASK_COMMAND") or "/usr/local/bin/agentbarn-task"


def _workspace() -> str:
    return os.environ.get("TERMINAL_CWD") or os.getcwd()


def _run(argv: list[str], stdin: str = "", timeout: float = _COMMAND_TIMEOUT_SECONDS) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [_command(), *argv],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_workspace(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Agent Barn Tasks are unavailable right now, so the change was not confirmed."
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "The Task command failed, so the change was not confirmed."
    return True, completed.stdout.strip()


def _argv(args: dict) -> tuple[list[str], str] | str:
    """The command line for one tool call, or what is missing from it.

    Option values are joined to their option (`--title=-v`) so a value starting with a
    dash is not read as another option.
    """
    action = args.get("action")
    task_id = args.get("task_id") or ""
    if action == "create":
        if not args.get("title"):
            return "create needs a title."
        argv = ["create", f"--title={args['title']}"]
        if args.get("description"):
            argv.append(f"--description={args['description']}")
        argv.append(f"--status={args['status'] if args.get('status') in _STATUSES else 'in_progress'}")
        if args.get("body"):
            argv.append(f"--note={args['body']}")
        return argv, ""
    if action == "list":
        return (["list", f"--status={args['status']}"] if args.get("status") else ["list"]), ""
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
            argv.append(f"--note={args['body']}")
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
            argv.append(f"--name={args['name']}")
        if args.get("content_type"):
            argv.append(f"--content-type={args['content_type']}")
        return [*argv, "--replace"], ""
    return "action must be one of: create, status, note, attach, remove_file, list, show."


def _handle_tool(args: dict, **_) -> str:
    built = _argv(args if isinstance(args, dict) else {})
    if isinstance(built, str):
        return json.dumps({"error": built})
    argv, stdin = built
    ok, output = _run(argv, stdin)
    if argv[0] not in {"list", "show"}:
        _forget_task_list()
    if not ok:
        return json.dumps({"error": output})
    try:
        return json.dumps(json.loads(output))
    except ValueError:
        return json.dumps({"result": output})


def _result(result) -> dict:
    """A tool's result as a dict; Hermes passes a JSON string."""
    try:
        answer = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


def _failed(result) -> bool:
    """Whether a tool call failed: an error, a patch that did not apply, or a command that exited non-zero."""
    answer = _result(result)
    exit_code = answer.get("exit_code")
    return (
        bool(answer.get("error")) or answer.get("success") is False or (isinstance(exit_code, int) and exit_code != 0)
    )


def _written_paths(args, result) -> list[str]:
    """The files a successful write or patch produced. A patch made from a patch body names its
    files only in the body, so the paths Hermes reports back are used when it gives them."""
    answer = _result(result)
    reported: list[str] = []
    for key in ("files_created", "files_modified"):
        value = answer.get(key)
        if isinstance(value, list):
            reported += [path for path in value if isinstance(path, str) and path]
    if reported:
        return reported
    path = args.get("path") if isinstance(args, dict) else None
    return [path] if isinstance(path, str) and path else []


def _published_paths(args) -> list[str]:
    """Files a shell command published with `agentbarn-artifacts upload`. Workflow uploads (with
    --attempt-id) belong to their run, not to a Task."""
    command = args.get("command") if isinstance(args, dict) else None
    if not isinstance(command, str):
        return []
    paths = []
    for match in _ARTIFACT_UPLOAD.finditer(command):
        try:
            words = shlex.split(match.group(1))
        except ValueError:
            continue
        if words and not any(word.startswith("--attempt-id") for word in words):
            paths.append(words[0])
    return paths


def _touches_tasks(tool_name: str, args) -> bool:
    if tool_name == _TOOL:
        return True
    command = args.get("command") if isinstance(args, dict) else None
    return isinstance(command, str) and "agentbarn-task" in command


def _records_task(tool_name: str, args, result) -> bool:
    """Whether a Task call changed a Task: a write that did not fail. Reading Tasks is not recording work."""
    if not isinstance(args, dict):
        return False
    if tool_name != _TOOL:
        command = args.get("command")
        return isinstance(command, str) and bool(_COMMAND_WRITE.search(command)) and not _failed(result)
    if args.get("action") not in _WRITE_ACTIONS:
        return False
    try:
        answer = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return True
    return not (isinstance(answer, dict) and "error" in answer)


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
        status = args["status"] if args.get("status") in _STATUSES else "in_progress"
    elif args.get("action") == "status" and args.get("status") in _STATUSES:
        status = args["status"]
    else:
        return None
    return _KEPT if status == "in_progress" and args.get("keep") in (True, "true") else status


def _track(
    tool_name: str = "", args=None, session_id: str = "", turn_id: str = "", tool_call_id: str = "", result=None
) -> dict:
    """Count one tool call in its turn. Safe to call twice for the same call."""
    _remember(_current_turn, session_id, turn_id)
    if (session_id, turn_id) not in _turns:
        _remember(_turns, (session_id, turn_id), _new_turn())
    turn = _turns[(session_id, turn_id)]
    if tool_name == _SCHEDULER_TOOL:
        _track_schedule(turn, args, result)
    if _touches_tasks(tool_name, args):
        if _records_task(tool_name, args, result):
            turn["recorded"] = True
            turn["attached"] |= _attached_names(tool_name, args)
            task_id = _task_id(tool_name, args, result)
            if task_id:
                turn["task_ids"].add(task_id)
                turn["last_task"] = task_id
                title = args.get("title") if isinstance(args, dict) else None
                if isinstance(title, str):
                    turn["titles"][task_id] = title
                status = _status_set(tool_name, args)
                if status:
                    turn["statuses"][task_id] = status
    else:
        if tool_call_id:
            turn["work"].add(tool_call_id)
        if tool_name in _FILE_TOOLS and not _failed(result):
            turn["wrote_files"] = True
            for path in _written_paths(args, result):
                turn["written"].add(os.path.normpath(os.path.join(_workspace(), path)))
        published = [] if _failed(result) else _published_paths(args)
        if published:
            turn["wrote_files"] = True
            for path in published:
                turn["written"].add(os.path.normpath(os.path.join(_workspace(), path)))
    return turn


def _track_schedule(turn: dict, args, result) -> None:
    """Remember a schedule the Agent created or removed with Hermes's scheduler tool."""
    if not isinstance(args, dict) or _failed(result):
        return
    if args.get("action") == "remove" and isinstance(args.get("job_id"), str):
        turn["removed_jobs"].add(args["job_id"])
        return
    if args.get("action") != "create":
        return
    try:
        created = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return
    if not isinstance(created, dict) or not isinstance(created.get("job_id"), str):
        return
    recurrence = str(created.get("schedule") or args.get("schedule") or "")
    repeat = args.get("repeat")
    limit = repeat if isinstance(repeat, int) and not isinstance(repeat, bool) and repeat > 0 else None
    turn["schedules"].append(
        {
            "job_id": created["job_id"],
            "name": str(created.get("name") or args.get("name") or ""),
            "recurrence": recurrence[:200],
            "run_limit": 1 if limit is None and recurrence.startswith("once") else limit,
        }
    )


def _home() -> str:
    return os.environ.get("HERMES_HOME") or "/opt/data"


def _links_path() -> str:
    return os.path.join(_home(), "agentbarn-task-schedules.json")


def _links() -> dict:
    """Job id -> {"task_id": ...}: the Tasks that follow a schedule. Kept beside the scheduler's own state."""
    try:
        with open(_links_path(), encoding="utf-8") as stored:
            links = json.load(stored)
    except (OSError, ValueError):
        return {}
    return links if isinstance(links, dict) else {}


def _save_links(links: dict) -> None:
    path = _links_path()
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as stored:
            json.dump(links, stored)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def _jobs() -> dict | None:
    """Hermes's scheduled jobs by id, or None when they cannot be read."""
    path = os.path.join(_home(), "cron", "jobs.json")
    try:
        with open(path, encoding="utf-8") as stored:
            data = json.load(stored)
    except (OSError, ValueError):
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        return None
    return {job["id"]: job for job in jobs if isinstance(job, dict) and isinstance(job.get("id"), str)}


def _end_link(links: dict, job_id: str, set_done: bool = True) -> None:
    """Stop following a schedule; its Task is done unless another schedule still feeds it."""
    link = links.pop(job_id, None)
    _save_links(links)
    if not link or not set_done:
        return
    if all(other.get("task_id") != link.get("task_id") for other in links.values()):
        _run(["status", link["task_id"], "done"])
        _forget_task_list()


def _link_schedules(session_id: str, turn: dict) -> None:
    """Decide, for each schedule created this turn, whether its runs are part of the Task for the request.

    A decision model reads the request once. Without its answer, a Task the Agent kept follows the schedule.
    """
    with _lock:
        request = _redacted(_requests.get(session_id, ""))
    for schedule in turn["schedules"]:
        task_id = turn["last_task"]
        agent_status = turn["statuses"].get(task_id) if task_id else None
        asked = {
            "request": request[:_AUTOMATIC_DESCRIPTION_CHARS],
            "schedule": {"recurrence": schedule["recurrence"], "run_limit": schedule["run_limit"]},
            "task": {
                "title": turn["titles"].get(task_id, "")[:500] if task_id else "",
                "status": "in_progress" if agent_status == _KEPT else (agent_status or ""),
            },
        }
        ok, output = _run(["schedule-intent"], stdin=json.dumps(asked), timeout=_INTENT_TIMEOUT_SECONDS)
        try:
            intent = json.loads(output).get("intent") if ok else None
        except (ValueError, AttributeError):
            intent = None
        if intent is None:
            intent = "runs" if agent_status == _KEPT else "setup"
        if intent != "runs":
            if agent_status == _KEPT:
                # Setting up the schedule was the whole job: the Task settles like any other.
                turn["statuses"][task_id] = "in_progress"
            continue
        if task_id is None:
            title = (schedule["name"] or " ".join(request.split()) or "Scheduled work")[:_AUTOMATIC_TITLE_CHARS]
            ok, output = _run(["create", f"--title={title}", "--status=in_progress", "--origin=automatic"])
            try:
                task_id = json.loads(output).get("id") if ok else None
            except (ValueError, AttributeError):
                task_id = None
            if not isinstance(task_id, str):
                continue
            turn["recorded"] = True
            turn["task_ids"].add(task_id)
            turn["last_task"] = task_id
        elif agent_status not in (_KEPT, "in_progress"):
            _run(["status", task_id, "in_progress"])
        turn["statuses"][task_id] = _KEPT
        links = _links()
        links[schedule["job_id"]] = {"task_id": task_id}
        _save_links(links)
        _forget_task_list()


def _settle_schedules(turn: dict | None) -> None:
    """Finish the Tasks of schedules the Agent removed this turn, or that ended since the plugin last looked."""
    links = _links()
    if not links:
        return
    jobs = _jobs()
    created = {schedule["job_id"] for schedule in turn["schedules"]} if turn is not None else set()
    for job_id in list(links):
        task_id = links[job_id].get("task_id")
        if job_id in created:
            continue
        if turn is not None and job_id in turn["removed_jobs"]:
            # A status the Agent set itself while removing the schedule stands.
            _end_link(links, job_id, set_done=task_id not in turn["statuses"])
        elif jobs is not None and (job_id not in jobs or jobs[job_id].get("state") == "completed"):
            _end_link(links, job_id)


def _record_scheduled_run(session_id: str, turn_id: str, job_id: str, turn: dict | None) -> bool:
    """Note a scheduled run on the Task that follows its schedule. False when no Task does."""
    links = _links()
    link = links.get(job_id)
    if not link or not isinstance(link.get("task_id"), str):
        return False
    task_id = link["task_id"]
    job: dict = (_jobs() or {}).get(job_id) or {}
    repeat = job.get("repeat")
    repeat = repeat if isinstance(repeat, dict) else {}
    completed, times, schedule = repeat.get("completed"), repeat.get("times"), job.get("schedule")
    done: int = completed if isinstance(completed, int) else int(link.get("runs") or 0)
    limit = times if isinstance(times, int) else None
    once = isinstance(schedule, dict) and schedule.get("kind") == "once"
    # Hermes counts a recurring run after it ends, and a one-off before it starts.
    number = done if once else done + 1
    with _lock:
        reply = " ".join(_redacted(_replies.pop((session_id, turn_id), "")).split())
    label = f"Run {number} of {limit}" if limit else f"Run {number}"
    _run(["note", task_id], stdin=f"{label}: {reply[:_RUN_NOTE_CHARS]}" if reply else f"{label}.")
    if turn is not None:
        turn["task_ids"] = {task_id}
        _attach_automatically(turn)
    if once or (limit is not None and number >= limit):
        _end_link(links, job_id)
    else:
        links[job_id] = {**link, "runs": number}
        _save_links(links)
        if turn is not None and turn["statuses"].get(task_id) not in (None, _KEPT, "in_progress", "failed"):
            # The schedule has runs left, so the Task is not finished whatever this run set.
            _run(["status", task_id, "in_progress"])
    _forget_task_list()
    return True


def _new_turn() -> dict:
    return {
        "work": set(),
        "wrote_files": False,
        "written": set(),
        "recorded": False,
        "task_ids": set(),
        # task_id -> the last status the Agent set this turn
        "statuses": {},
        "attached": set(),
        "reminded": False,
        "held": False,
        # The Task the Agent touched last, and the titles it gave the Tasks it created.
        "last_task": None,
        "titles": {},
        # Schedules the Agent created this turn, and the ids of those it removed.
        "schedules": [],
        "removed_jobs": set(),
    }


def _unrecorded_work(turn: dict | None) -> bool:
    return bool(turn) and not turn["recorded"] and (turn["wrote_files"] or len(turn["work"]) >= _WORK_THRESHOLD)


def _unattached(turn: dict) -> list[tuple[str, str]]:
    """The turn's written files, by name and path, that it has not attached and may attach."""
    written = sorted((os.path.basename(path), path) for path in turn["written"])
    return [(name, path) for name, path in written if name not in turn["attached"] and not _CREDENTIAL_FILE.match(name)]


def _attach_reminder(names: list[str]) -> str:
    return (
        f"These files you produced are not on a Task yet: {', '.join(names)}. Attach the ones that are part of "
        "the result with the agentbarn_task tool (action attach)."
    )


def _attach_automatically(turn: dict) -> list[str]:
    """Attach the turn's files to the one Task it touched. Returns the names it could not attach."""
    unattached = _unattached(turn)
    if len(turn["task_ids"]) != 1:
        return [name for name, _ in unattached]
    (task_id,) = turn["task_ids"]
    limit = os.environ.get("ARTIFACT_MAX_BYTES", "")
    names = [name for name, _ in unattached]
    failed = []
    for name, path in unattached:
        if not os.path.isfile(path):
            continue
        if limit.isdigit() and os.path.getsize(path) > int(limit):
            failed.append(name)
            continue
        # A newer copy replaces the Task's file of the same name, unless this turn wrote two
        # files of that name in different folders: then both are kept.
        replace = ["--replace"] if names.count(name) == 1 else []
        ok, _ = _run(["attach", task_id, path, *replace])
        if not ok:
            failed.append(name)
    return failed


def _settle_in_progress(turn: dict, status: str) -> None:
    """Move each Task the Agent left in_progress this turn to `status`; a status it chose itself stays.

    A Task it kept stays in_progress, unless the turn did not complete: then it is reopened too.
    """
    settled = False
    settles = {"in_progress", _KEPT} if status == "open" else {"in_progress"}
    for task_id, current in sorted(turn["statuses"].items()):
        if current in settles:
            _run(["status", task_id, status])
            settled = True
    if settled:
        _forget_task_list()


def _record_automatically(session_id: str, turn: dict) -> list[str]:
    """Record a Task for work the Agent left unrecorded. Returns the files it could not attach."""
    with _lock:
        request = " ".join(_redacted(_requests.get(session_id, "")).split())
    title = request or "Work recorded automatically"
    if len(title) > _AUTOMATIC_TITLE_CHARS:
        title = title[: _AUTOMATIC_TITLE_CHARS - 1].rstrip() + "…"
    argv = ["create", f"--title={title}", "--status=done", "--origin=automatic"]
    if request:
        argv.append(f"--description={request[:_AUTOMATIC_DESCRIPTION_CHARS]}")
    ok, output = _run(argv)
    _forget_task_list()
    try:
        task_id = json.loads(output).get("id") if ok else None
    except (ValueError, AttributeError):
        task_id = None
    if not isinstance(task_id, str):
        return [name for name, _ in _unattached(turn)]
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


def _on_post_llm_call(session_id="", turn_id="", assistant_response="", **_):
    if isinstance(assistant_response, str) and _CRON_SESSION.match(session_id or ""):
        with _lock:
            _remember(_replies, (session_id, turn_id), assistant_response[:_AUTOMATIC_DESCRIPTION_CHARS])


def _on_session_end(session_id="", turn_id="", completed=False, **_):
    """Hermes fires this at the end of every turn, despite its name.

    A turn's files go to the one Task it touched without asking the model; the Agent can
    remove any that are not part of the result. Work the Agent did not record at all is
    recorded automatically. Only what could not be attached is named on the next turn.
    """
    with _lock:
        side = _side_runs.pop((session_id, turn_id), None) or session_id == _BOOT_SESSION_ID
        turn = _turns.pop((session_id, turn_id), None)
        if _current_turn.get(session_id) == turn_id:
            del _current_turn[session_id]
    if side:
        return
    scheduled = _CRON_SESSION.match(session_id or "")
    if scheduled:
        with _lock:
            noted = session_id in _noted_runs
            if not noted and scheduled.group(1) in _links():
                _remember(_noted_runs, session_id, True)
        if noted or _record_scheduled_run(session_id, turn_id, scheduled.group(1), turn):
            return
    if not scheduled:
        if turn is not None and completed and turn["schedules"]:
            _link_schedules(session_id, turn)
        _settle_schedules(turn)
    if turn is None:
        return
    if completed and _unrecorded_work(turn):
        failed = _record_automatically(session_id, turn)
    elif turn["recorded"]:
        # A turn that failed or was interrupted leaves its Task open to pick up again, not in progress.
        failed = _attach_automatically(turn)
        _settle_in_progress(turn, "done" if completed else "open")
    else:
        return
    if failed:
        with _lock:
            _remember(_next_turn_reminders, session_id, _attach_reminder(failed) + _QUIET)


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


def _task_lines(output: str) -> list[str]:
    """The open Tasks, then the latest finished ones, from one listing (most recently changed first)."""
    try:
        items = json.loads(output)["items"]
    except (ValueError, KeyError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    lines = []
    for task_status in ("in_progress", "open", "done"):
        shown = [task for task in items if isinstance(task, dict) and task.get("status") == task_status]
        for task in shown[: _DONE_TASKS_SHOWN if task_status == "done" else _OPEN_TASKS_SHOWN]:
            title = str(task.get("title", ""))[:120]
            note = "" if task_status == "done" else _note_preview(task.get("latest_note"))
            lines.append(f"- {task.get('id')} [{task_status}] {title}{note}")
    return lines


def _note_preview(note) -> str:
    text = " ".join(note.split()) if isinstance(note, str) else ""
    if not text:
        return ""
    shown = text[:_LATEST_NOTE_CHARS] + ("…" if len(text) > _LATEST_NOTE_CHARS else "")
    return f' (latest note: "{shown}")'


def _open_task_lines() -> list[str]:
    with _lock:
        read_at = _task_list_cache["at"]
        if read_at is not None and time.monotonic() - read_at < _OPEN_TASKS_TTL_SECONDS:
            return _task_list_cache["lines"]
    ok, output = _run(["list", f"--page-size={_LIST_PAGE_SIZE}"], timeout=_LIST_TIMEOUT_SECONDS)
    lines = _task_lines(output) if ok else []
    with _lock:
        _task_list_cache.update({"at": time.monotonic(), "lines": lines})
    return lines


def _small_talk(message) -> bool:
    words = re.findall(r"[a-z]+", message.lower().replace("'", "")) if isinstance(message, str) else []
    return 0 < len(words) <= _SMALL_TALK_MAX_WORDS and all(word in _SMALL_TALK_WORDS for word in words)


def _on_pre_llm_call(session_id="", turn_id="", user_message="", parent_session_id="", **_):
    if session_id == _BOOT_SESSION_ID:
        return None
    if parent_session_id:
        with _lock:
            _remember(_side_runs, (session_id, turn_id), True)
        return None
    if isinstance(user_message, str):
        with _lock:
            _remember(_requests, session_id, user_message[:_AUTOMATIC_DESCRIPTION_CHARS])
    parts = [] if _small_talk(user_message) else ["[Agent Barn] " + _REQUEST_LINE]
    lines = _open_task_lines()
    if lines:
        parts.append(
            "[Agent Barn] Your open and latest finished Tasks:\n"
            + "\n".join(lines)
            + "\nKeep using one of these only when the request is the same piece of work: set it to in_progress "
            "with the agentbarn_task tool, with keep: true if the work still continues after this turn. A new "
            "request gets its own Task, even while another is in progress."
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
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("pre_verify", _on_pre_verify)
