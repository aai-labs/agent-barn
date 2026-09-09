"""Shared runtime client, execution bindings, and durable scheduled-result spool.

Provider credentials never enter this module. Runtime adapters bind interactive
sessions; the model-facing CLI has no execution/origin/idempotency options.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path


def request(method, path, payload=None):
    url = os.environ["COMMUNICATIONS_URL"].rstrip("/")
    agent = os.environ["AGENT_ID"]
    req = urllib.request.Request(
        f"{url}/agents/{agent}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['COMMUNICATIONS_API_KEY']}",
            "Content-Type": "application/json",
            "X-AgentBarn-Communications-Version": "2",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def _binding_path(session):
    root = Path(os.environ.get("AGENTBARN_EXECUTIONS_DIR", "/tmp/agentbarn-executions"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root / hashlib.sha256(session.encode()).hexdigest()


def bind_execution(session, delivery):
    path = _binding_path(session)
    token = delivery.get("execution_token")
    if not token:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"token": token, "delivery_id": delivery["delivery_id"]}))
    temporary.chmod(0o600)
    temporary.replace(path)


def unbind_execution(session):
    _binding_path(session).unlink(missing_ok=True)


def execution_environment(session, invocation):
    if not session or not invocation:
        raise ValueError("Message sending requires a runtime-bound inbound tool invocation")
    bound = json.loads(_binding_path(session).read_text())
    return {
        "AGENTBARN_EXECUTION_TOKEN": bound["token"],
        "AGENTBARN_INVOCATION_ID": f"{bound['delivery_id']}:{invocation}",
    }


def send_explicit(recipient, text, kind="channel", thread=None):
    target = {"kind": kind, "recipient": recipient}
    if thread:
        target["thread_id"] = thread
    if os.environ.get("AGENTBARN_TOOL_SESSION"):
        os.environ.update(
            execution_environment(os.environ["AGENTBARN_TOOL_SESSION"], os.environ.get("AGENTBARN_TOOL_INVOCATION"))
        )
    receipt = request(
        "POST",
        "messages",
        {
            "text": text,
            "idempotency_key": os.environ["AGENTBARN_INVOCATION_ID"],
            "destination": {"kind": "explicit", "target": target},
            "context": {"kind": "interactive", "execution_token": os.environ["AGENTBARN_EXECUTION_TOKEN"]},
        },
    )
    return receipt


@contextmanager
def _spool():
    default = str(Path(os.environ.get("HERMES_HOME", "/opt/data")) / "agentbarn-messages.sqlite3")
    path = Path(os.environ.get("AGENTBARN_MESSAGE_SPOOL", default))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS completions (
        run_id TEXT PRIMARY KEY, request TEXT NOT NULL, receipt TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0, error TEXT
    )""")
    try:
        with db:
            yield db
    finally:
        db.close()


# Every silence token in play: the runtime's own set (models routinely drop the
# brackets), plus HEARTBEAT_OK from the predefined templates. Matched trimmed and
# case-insensitively on the whole response or its first/last line, mirroring
# gateway.response_filters so the bridge never delivers what native delivery would
# have swallowed.
SILENCE_MARKERS = frozenset({"[silent]", "silent", "no_reply", "no reply", "heartbeat_ok"})


def is_silent(text):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return True
    return any(candidate.casefold() in SILENCE_MARKERS for candidate in (text.strip(), lines[0], lines[-1]))


_KEEP_ORIGIN_THREAD = object()


def _requested_thread(deliver, channel_id):
    """The thread a job asked for inside its own channel, or None for the channel root.

    `deliver` may only move a message within the channel the conversation already
    admitted -- a thread and its channel root are the same outbound policy decision,
    since validate_outbound_target never inspects thread_id. Naming any other channel
    raises: quietly falling back to the origin thread is how a message ends up
    somewhere the author did not ask for and cannot see.
    """
    value = str(deliver or "").strip()
    if not value or "," in value or ":" not in value:
        return _KEEP_ORIGIN_THREAD  # "origin", "local", "all", a bare platform, or fan-out
    _, _, remainder = value.partition(":")
    chat, _, thread = remainder.partition(":")
    if chat.strip() != channel_id:
        raise ValueError("deliver names a channel outside the job's origin")
    return thread.strip() or None


def destination_for_origin(origin, deliver=None):
    """Where a scheduled completion goes, from what the runtime recorded at create time.

    No origin means the job was created outside any conversation (BOOT.md at first
    start), so it belongs to the configured default. An origin we cannot map is NOT
    the default: the job was created somewhere, and delivering it elsewhere would put
    it in front of people who never asked for it. Return None so the caller refuses.
    """
    if not origin:
        return {"kind": "default"}
    chat_id = str(origin.get("chat_id") or "")
    if origin.get("platform") != "api_server" or not chat_id.startswith("connection:"):
        return None
    parts = chat_id.split(":", 3)
    if len(parts) != 4 or not parts[1] or not parts[2]:
        return None
    _, connection_id, channel_id, thread_id = parts
    try:
        requested = _requested_thread(deliver, channel_id)
    except ValueError:
        return None
    origin_thread = None if thread_id == "root" else thread_id
    return {
        "kind": "origin",
        "connection_id": connection_id,
        "channel_id": channel_id,
        "thread_id": origin_thread if requested is _KEEP_ORIGIN_THREAD else requested,
    }


def capture_completion(run_id, text, origin=None, deliver=None):
    if is_silent(text):
        return
    destination = destination_for_origin(origin, deliver)
    if destination is None:
        print("[agentbarn-message] scheduled completion has an unrecognized origin; not delivered", flush=True)
        return
    if not run_id:
        raise ValueError("Scheduled completion has no durable run identity")
    payload = json.dumps(
        {
            "text": text,
            "idempotency_key": f"scheduled:{run_id}",
            "destination": destination,
            "context": {"kind": "scheduled", "run_id": str(run_id)},
        },
        sort_keys=True,
    )
    with _spool() as db:
        existing = db.execute("SELECT request FROM completions WHERE run_id=?", (str(run_id),)).fetchone()
        if existing and existing[0] != payload:
            raise ValueError("Scheduled run identity already contains a different completion")
        db.execute("INSERT OR IGNORE INTO completions(run_id, request) VALUES (?, ?)", (str(run_id), payload))


def drain_once():
    with _spool() as db:
        rows = db.execute(
            "SELECT run_id, request, attempts FROM completions WHERE receipt IS NULL AND available_at<=? "
            "ORDER BY rowid LIMIT 20",
            (time.time(),),
        ).fetchall()
    for run_id, payload, attempts in rows:
        try:
            receipt = request("POST", "messages", json.loads(payload))
            if not isinstance(receipt, dict) or not receipt.get("delivery_id") or not receipt.get("status"):
                raise ValueError("Communications did not acknowledge durable acceptance")
        except Exception as exc:
            # Retain the body locally, but never print content, credentials, or provider errors.
            with _spool() as db:
                db.execute(
                    "UPDATE completions SET attempts=attempts+1, available_at=?, error=? WHERE run_id=?",
                    (time.time() + min(300, 2 ** min(attempts + 1, 8)), type(exc).__name__, run_id),
                )
            print(f"[agentbarn-message] scheduled submission pending ({type(exc).__name__})", flush=True)
        else:
            with _spool() as db:
                db.execute("UPDATE completions SET receipt=?, error=NULL WHERE run_id=?", (json.dumps(receipt), run_id))


def drain_forever():
    while True:
        try:
            drain_once()
        except Exception as exc:
            print(f"[agentbarn-message] spool unavailable ({type(exc).__name__})", flush=True)
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(prog="agentbarn-message")
    sub = parser.add_subparsers(dest="action", required=True)
    send = sub.add_parser("send")
    send.add_argument("--to", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--kind", choices=["channel", "user", "dm"], default="channel")
    send.add_argument("--thread")
    sub.add_parser("drain")
    args = parser.parse_args()
    if args.action == "drain":
        drain_forever()
    else:
        try:
            print(json.dumps(send_explicit(args.to, args.text, args.kind, args.thread)))
        except Exception as exc:
            parser.exit(1, f"Message was not acknowledged ({type(exc).__name__}); retry the same tool invocation.\n")


if __name__ == "__main__":
    main()
