"""Record this Agent's own Tasks, their status, notes and files, for both Agent runtimes."""

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

STATUSES = ("open", "in_progress", "done", "failed")
NOTE_LIMIT = 10000
UNCONFIRMED = "Agent Barn Tasks are unavailable right now, so the change was not confirmed. Try again shortly."


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def refusal(error: urllib.error.HTTPError) -> str:
    """A clear message for each refusal. Only the service's own 400 and 422 explanations are passed on."""
    try:
        detail = json.loads(error.read(65536)).get("detail")
    except (OSError, ValueError, AttributeError):
        detail = None
    if error.code == 400 and isinstance(detail, str):
        return detail
    if error.code == 422 and isinstance(detail, list):
        messages = [item.get("msg") for item in detail if isinstance(item, dict) and isinstance(item.get("msg"), str)]
        if messages:
            return "The request was refused: " + "; ".join(messages)
    return {
        401: "This Agent's Task credential was refused. Restart this Agent.",
        404: "Task not found. Run `agentbarn-task list` to find your Task ids.",
    }.get(error.code, UNCONFIRMED)


def fetch(request: urllib.request.Request):
    """The JSON response, or the message to report instead."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=120) as response:
            if response.status == 204:
                return True, None
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Response too large")
            return True, json.loads(raw)
    except urllib.error.HTTPError as error:
        return False, refusal(error)
    except (OSError, ValueError):
        return False, UNCONFIRMED


def send(request: urllib.request.Request) -> int:
    ok, result = fetch(request)
    if not ok:
        return fail(result)
    print(json.dumps(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record this Agent's Tasks: create, update, note, attach, read.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Open a Task and print it, with its id.")
    create.add_argument("--title", required=True)
    create.add_argument("--description")
    create.add_argument("--status", choices=STATUSES, help="Start the Task in this status rather than open.")
    status = commands.add_parser("status", help="Change a Task's status.")
    status.add_argument("task_id")
    status.add_argument("status", choices=STATUSES)
    note = commands.add_parser("note", help="Add a note to a Task, read from standard input.")
    note.add_argument("task_id")
    attach = commands.add_parser("attach", help="Attach a file to a Task.")
    attach.add_argument("task_id")
    attach.add_argument("path")
    attach.add_argument("--name", help="The file's name as shown on the Task. Defaults to the file's own name.")
    attach.add_argument("--content-type", help="A bare type/subtype. Guessed from the name when left out.")
    listing = commands.add_parser("list", help="List this Agent's Tasks, newest first.")
    listing.add_argument("--status", choices=STATUSES)
    show = commands.add_parser("show", help="Show one Task with its notes and files.")
    show.add_argument("task_id")
    remove = commands.add_parser("remove-file", help="Remove a file from a Task, by the file id `show` lists.")
    remove.add_argument("task_id")
    remove.add_argument("file_id")
    args = parser.parse_args()

    agent_id = os.environ.get("AGENT_ID", "")
    url = os.environ.get("INGEST_URL", "").rstrip("/")
    key = os.environ.get("INGEST_API_KEY", "")
    parts = urlsplit(url)
    if (
        not agent_id
        or not key
        or parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.query
        or parts.fragment
    ):
        return fail("Agent Barn Tasks are not configured for this Agent. Restart this Agent.")
    tasks_url = f"{url}/agents/{quote(agent_id, safe='')}/tasks"
    task_url = f"{tasks_url}/{quote(getattr(args, 'task_id', ''), safe='')}"
    headers = {"Authorization": "Bearer " + key}

    def json_request(target: str, method: str, payload: dict | None = None) -> urllib.request.Request:
        data = None if payload is None else json.dumps(payload).encode()
        return urllib.request.Request(
            target, data=data, headers={**headers, "Content-Type": "application/json"}, method=method
        )

    if args.command == "create":
        payload = {"title": args.title}
        if args.description:
            payload["description"] = args.description
        if not args.status or args.status == "open":
            return send(json_request(tasks_url, "POST", payload))
        ok, created = fetch(json_request(tasks_url, "POST", payload))
        if not ok:
            return fail(created)
        task_id = created.get("id") if isinstance(created, dict) else None
        if not isinstance(task_id, str):
            return fail(UNCONFIRMED)
        ok, updated = fetch(json_request(f"{tasks_url}/{quote(task_id, safe='')}", "PATCH", {"status": args.status}))
        if not ok:
            return fail(f"The Task {task_id} was created but its status was not set: {updated}")
        print(json.dumps(updated))
        return 0
    if args.command == "status":
        return send(json_request(task_url, "PATCH", {"status": args.status}))
    if args.command == "note":
        raw = sys.stdin.read(NOTE_LIMIT + 1)
        body = raw.strip()
        if not body or len(raw) > NOTE_LIMIT:
            return fail(f"Provide the note, between 1 and {NOTE_LIMIT} characters, on standard input.")
        return send(json_request(f"{task_url}/notes", "POST", {"body": body}))
    if args.command == "list":
        query = f"?{urlencode({'status': args.status})}" if args.status else ""
        return send(json_request(tasks_url + query, "GET"))
    if args.command == "show":
        return send(json_request(task_url, "GET"))
    if args.command == "remove-file":
        ok, result = fetch(json_request(f"{task_url}/files/{quote(args.file_id, safe='')}", "DELETE"))
        if not ok:
            return fail(result)
        print(json.dumps({"removed": args.file_id}))
        return 0

    path = Path(args.path)
    if not path.is_file():
        return fail(f"{args.path} is not a file.")
    size = path.stat().st_size
    limit = os.environ.get("TASK_FILE_MAX_BYTES", "")
    if limit.isdigit() and size > int(limit):
        # Refused here rather than mid-upload, where the refusal could arrive as a reset connection.
        return fail(f"The file is larger than the {limit}-byte limit.")
    name = args.name or path.name
    content_type = args.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    with path.open("rb") as upload:
        request = urllib.request.Request(
            f"{task_url}/files?{urlencode({'filename': name})}",
            data=upload,
            headers={**headers, "Content-Type": content_type, "Content-Length": str(size)},
            method="POST",
        )
        return send(request)


if __name__ == "__main__":
    raise SystemExit(main())
