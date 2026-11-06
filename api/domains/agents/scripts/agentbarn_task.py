"""Record this Agent's own Tasks, their status, notes and files, for both Agent runtimes."""

import argparse
import hashlib
import json
import mimetypes
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

STATUSES = ("open", "in_progress", "done", "failed")
ORIGINS = ("agent", "automatic")
NOTE_LIMIT = 10000
UNCONFIRMED = "Agent Barn Tasks are unavailable right now, so the change was not confirmed. Try again shortly."
NO_FILE_STORAGE = (
    "Files cannot be attached: file storage is not set up for this Agent. Record the work on the Task without the file."
)


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


def publish_refusal(error: urllib.error.HTTPError) -> str:
    """A clear message for a refused publish. The storage service's own wording is not passed on."""
    if error.code == 422:
        return refusal(error)
    return {
        401: "This Agent's file credential was refused. Restart this Agent.",
        413: "The file is larger than this Agent's file limit.",
        503: "File storage for this Agent is not available right now, so the file was not attached. Try again shortly.",
    }.get(error.code, "The file was not stored, so it was not attached. Try again shortly.")


def read_workspace_file(path: Path, max_bytes: int) -> bytes:
    """The file's bytes, if it is a regular file inside the workspace and within the limit.

    The same rules as the Artifact command: links are resolved first, so a link out of the
    workspace is refused, and the final component is opened without following a link.
    """
    roots = [
        Path(item).resolve() for item in os.environ.get("ARTIFACT_UPLOAD_ROOTS", str(Path.cwd())).split(":") if item
    ]
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError(f"{path} is not a file.") from None
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError(f"Attach a file inside your workspace ({', '.join(str(root) for root in roots)}).")
    try:
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError(f"{path} is not a file.") from None
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"{path} is not a file.")
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        # Refused here rather than mid-upload, where the refusal could arrive as a reset connection.
        raise ValueError(f"The file is larger than the {max_bytes}-byte limit.")
    return content


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
    create.add_argument("--note", help="Add this note to the new Task.")
    create.add_argument(
        "--origin", choices=ORIGINS, help="automatic when the Task plugin records work the Agent did not."
    )
    status = commands.add_parser("status", help="Change a Task's status.")
    status.add_argument("task_id")
    status.add_argument("status", choices=STATUSES)
    status.add_argument("--note", help="Add this note to the Task, for example why it failed.")
    note = commands.add_parser("note", help="Add a note to a Task, read from standard input.")
    note.add_argument("task_id")
    attach = commands.add_parser("attach", help="Attach a file to a Task.")
    attach.add_argument("task_id")
    attach.add_argument("path")
    attach.add_argument("--name", help="The file's name as shown on the Task. Defaults to the file's own name.")
    attach.add_argument("--content-type", help="A bare type/subtype. Guessed from the name when left out.")
    attach.add_argument(
        "--replace", action="store_true", help="Remove the Task's earlier files of the same name once this one is in."
    )
    listing = commands.add_parser("list", help="List this Agent's Tasks, most recently changed first.")
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--page-size", type=int, choices=range(1, 101), metavar="1-100")
    show = commands.add_parser("show", help="Show one Task with its notes and files.")
    show.add_argument("task_id")
    remove = commands.add_parser("remove-file", help="Remove a file from a Task, by the file id `show` lists.")
    remove.add_argument("task_id")
    remove.add_argument("file_id")
    args = parser.parse_args()
    note_text = (getattr(args, "note", None) or "").strip()
    if getattr(args, "note", None) is not None and (not note_text or len(args.note) > NOTE_LIMIT):
        return fail(f"Provide the note, between 1 and {NOTE_LIMIT} characters.")

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

    def add_note(target: str) -> str | None:
        """Post the --note, if any. Returns why it was not recorded."""
        if not note_text:
            return None
        ok, result = fetch(json_request(f"{target}/notes", "POST", {"body": note_text}))
        return None if ok else result

    if args.command == "create":
        payload = {"title": args.title}
        if args.description:
            payload["description"] = args.description
        if args.origin:
            payload["origin"] = args.origin
        if args.status:
            payload["status"] = args.status
        if not note_text:
            return send(json_request(tasks_url, "POST", payload))
        ok, task = fetch(json_request(tasks_url, "POST", payload))
        if not ok:
            return fail(task)
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str):
            return fail(UNCONFIRMED)
        refused = add_note(f"{tasks_url}/{quote(task_id, safe='')}")
        if refused:
            return fail(f"The Task {task_id} was created but the note was not recorded: {refused}")
        print(json.dumps(task))
        return 0
    if args.command == "status":
        ok, task = fetch(json_request(task_url, "PATCH", {"status": args.status}))
        if not ok:
            return fail(task)
        refused = add_note(task_url)
        if refused:
            return fail(f"The status was set to {args.status} but the note was not recorded: {refused}")
        print(json.dumps(task))
        return 0
    if args.command == "note":
        raw = sys.stdin.read(NOTE_LIMIT + 1)
        body = raw.strip()
        if not body or len(raw) > NOTE_LIMIT:
            return fail(f"Provide the note, between 1 and {NOTE_LIMIT} characters, on standard input.")
        return send(json_request(f"{task_url}/notes", "POST", {"body": body}))
    if args.command == "list":
        filters = {"status": args.status, "page_size": args.page_size}
        query = urlencode({name: value for name, value in filters.items() if value is not None})
        return send(json_request(f"{tasks_url}?{query}" if query else tasks_url, "GET"))
    if args.command == "show":
        return send(json_request(task_url, "GET"))
    if args.command == "remove-file":
        ok, result = fetch(json_request(f"{task_url}/files/{quote(args.file_id, safe='')}", "DELETE"))
        if not ok:
            return fail(result)
        print(json.dumps({"removed": args.file_id}))
        return 0

    artifact_url = os.environ.get("ARTIFACT_URL", "").rstrip("/")
    artifact_key = os.environ.get("ARTIFACT_API_KEY", "")
    artifact_parts = urlsplit(artifact_url)
    if (
        not artifact_key
        or artifact_parts.scheme not in {"http", "https"}
        or not artifact_parts.netloc
        or artifact_parts.username
        or artifact_parts.query
        or artifact_parts.fragment
    ):
        return fail(NO_FILE_STORAGE)
    limit = os.environ.get("ARTIFACT_MAX_BYTES", "")
    try:
        content = read_workspace_file(Path(args.path), int(limit) if limit.isdigit() else 25 * 1024 * 1024)
    except ValueError as error:
        return fail(str(error))
    name = args.name or Path(args.path).name
    content_type = args.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    earlier = []
    if args.replace:
        ok, task = fetch(json_request(task_url, "GET"))
        if not ok:
            return fail(task)
        files = task.get("files") if isinstance(task, dict) else None
        earlier = [
            item["id"]
            for item in files or []
            if isinstance(item, dict) and item.get("filename") == name and isinstance(item.get("id"), str)
        ]
    # The bytes go to Artifact storage first; the Task then records the Artifact by id.
    artifact_headers = {"Authorization": "Bearer " + artifact_key}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        metadata = {
            "filename": name,
            "content_type": content_type,
            "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
        }
        create_request = urllib.request.Request(
            f"{artifact_url}/artifacts",
            data=json.dumps(metadata).encode(),
            headers={**artifact_headers, "Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(create_request, timeout=120) as response:
            artifact_id = json.loads(response.read(1_000_000))["id"]
        content_request = urllib.request.Request(
            f"{artifact_url}/artifacts/{quote(str(artifact_id), safe='')}/content",
            data=content,
            headers={**artifact_headers, "Content-Type": "application/octet-stream"},
            method="PUT",
        )
        with opener.open(content_request, timeout=120) as response:
            published = json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as error:
        return fail(publish_refusal(error))
    except (OSError, ValueError, KeyError, TypeError):
        return fail("The file was not stored, so it was not attached. Try again shortly.")
    if not isinstance(published, dict) or published.get("state") != "READY":
        return fail("The file was not stored, so it was not attached. Try again shortly.")
    ok, attached = fetch(json_request(f"{task_url}/files", "POST", {"artifact_id": str(artifact_id)}))
    if not ok:
        return fail(attached)
    # Removed only once the new file is in, so a refused upload leaves the earlier one in place.
    for file_id in earlier:
        ok, refused = fetch(json_request(f"{task_url}/files/{quote(file_id, safe='')}", "DELETE"))
        if not ok:
            return fail(f"The file was attached but its earlier copy was not removed: {refused}")
    print(json.dumps(attached))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
