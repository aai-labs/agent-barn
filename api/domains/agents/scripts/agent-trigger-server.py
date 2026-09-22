"""Private, authenticated ingress for immediate one-shot Agent triggers.

Agent Barn only learns whether the native scheduler accepted the trigger. Hermes or
OpenClaw owns execution, delivery through the selected native channel, and run history.
"""

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

PORT = int(os.environ.get("AGENT_TRIGGER_PORT", "8082"))
TRIGGER_KEY = os.environ.get("AGENT_TRIGGER_KEY", "")
RUNTIME_KIND = os.environ.get("RUNTIME_KIND", "")
RUNTIME_API_KEY = os.environ.get("RUNTIME_API_KEY", "")
RUNTIME_API_URL = os.environ.get("RUNTIME_API_URL", "").rstrip("/")
RECEIPT_PATH = Path(os.environ.get("AGENT_TRIGGER_RECEIPT_PATH", "/tmp/agent-trigger-receipts.sqlite3"))
MAX_BODY_BYTES = 128 * 1024
PLATFORMS = {"slack", "discord", "telegram", "teams"}
# ponytail: one process-wide lock serializes every dispatch, including its runtime
# calls (up to ~15s). Fine at webhook volume; lock per idempotency key if it queues.
_LOCK = threading.Lock()


class DispatchError(RuntimeError):
    pass


class NotSubmittedError(DispatchError):
    """The runtime certainly created no job, so the same key may safely try again."""


class RuntimeRejectedError(ValueError):
    """The runtime refused the job (4xx); it created nothing and will refuse again."""


class ConflictError(ValueError):
    pass


def _database() -> sqlite3.Connection:
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(RECEIPT_PATH)
    # native_job_id is NULL while a create is in flight or its outcome is unknown.
    db.execute(
        "CREATE TABLE IF NOT EXISTS trigger_receipts ("
        "idempotency_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, native_job_id TEXT)"
    )
    db.commit()
    return db


def _request_json(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{RUNTIME_API_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {RUNTIME_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            decoded = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # A 4xx (e.g. Hermes' 5,000-character prompt cap) will fail the same way on retry.
        if 400 <= exc.code < 500:
            raise RuntimeRejectedError(f"Hermes rejected the trigger with HTTP {exc.code}") from exc
        raise DispatchError("Hermes scheduler rejected the trigger") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            raise NotSubmittedError("Hermes scheduler is not accepting connections") from exc
        raise DispatchError("Hermes scheduler rejected the trigger") from exc
    except (OSError, ValueError) as exc:
        raise DispatchError("Hermes scheduler rejected the trigger") from exc
    if not isinstance(decoded, dict):
        raise DispatchError("Hermes scheduler returned an invalid response")
    return decoded


def _job_name(invocation_id: str, generation: int) -> str:
    return f"agentbarn-hook-{invocation_id.replace('-', '')}-{generation}"


def _run_at() -> str:
    # The native scheduler fires the one-shot itself. A forced "run now" is avoided:
    # OpenClaw preserves a future one-shot schedule after a forced run (so the job
    # would fire again later), and OpenClaw never schedules an `at` in the past.
    return (datetime.now(UTC) + timedelta(seconds=5)).isoformat().replace("+00:00", "Z")


def _job_id(job: object, runtime: str) -> str:
    job_id = str(job.get("id") or job.get("jobId") or "") if isinstance(job, dict) else ""
    if not job_id:
        raise DispatchError(f"{runtime} job has no identifier")
    return job_id


def _hermes_find(name: str) -> str | None:
    jobs = _request_json("GET", "/api/jobs?include_disabled=true").get("jobs", [])
    existing = next((job for job in jobs if isinstance(job, dict) and job.get("name") == name), None)
    return None if existing is None else _job_id(existing, "Hermes")


def _hermes_create(name: str, prompt: str, platform: str) -> str:
    created = _request_json(
        "POST",
        "/api/jobs",
        {
            "name": name,
            "schedule": _run_at(),
            "prompt": prompt,
            "deliver": platform,
            "repeat": 1,
        },
    ).get("job")
    return _job_id(created, "Hermes")


def _openclaw_json(arguments: list[str]) -> object:
    try:
        completed = subprocess.run(
            ["openclaw", "automations", *arguments, "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return json.loads(completed.stdout)
    except FileNotFoundError as exc:
        raise NotSubmittedError("OpenClaw CLI is not available") from exc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise DispatchError("OpenClaw scheduler rejected the trigger") from exc


def _openclaw_jobs(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        values = payload.get("jobs")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def _openclaw_find(name: str) -> str | None:
    existing = next((job for job in _openclaw_jobs(_openclaw_json(["list", "--all"])) if job.get("name") == name), None)
    return None if existing is None else _job_id(existing, "OpenClaw")


def _openclaw_create(name: str, prompt: str, platform: str) -> str:
    channel = "msteams" if platform == "teams" else platform
    created = _openclaw_json(
        [
            "create",
            "--at",
            _run_at(),
            "--message",
            prompt,
            "--name",
            name,
            "--session",
            "isolated",
            "--announce",
            "--channel",
            channel,
        ]
    )
    return _job_id(created.get("job", created) if isinstance(created, dict) else None, "OpenClaw")


def dispatch(idempotency_key: str, payload: dict) -> str:
    """Submit at most one native job per idempotency key.

    A pending receipt is committed before the create call. If a retry finds it
    pending and the runtime has no job by that name, the first create may still
    have run (one-shot jobs delete themselves), so the outcome is reported as
    unknown instead of risking a second run. A failure that proves nothing was
    created drops the receipt, so a retry of the same key submits normally.
    """
    if RUNTIME_KIND == "hermes":
        find, create = _hermes_find, _hermes_create
    elif RUNTIME_KIND == "openclaw":
        find, create = _openclaw_find, _openclaw_create
    else:
        raise DispatchError("Unsupported Agent runtime")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload_hash = hashlib.sha256(encoded).hexdigest()
    with _LOCK, closing(_database()) as db:
        receipt = db.execute(
            "SELECT payload_hash, native_job_id FROM trigger_receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if receipt is not None:
            if not hmac.compare_digest(receipt[0], payload_hash):
                raise ConflictError("Idempotency key was already used for another trigger")
            if receipt[1] is not None:
                return str(receipt[1])

        name = _job_name(payload["invocation_id"], payload["dispatch_generation"])
        native_job_id = find(name)
        if native_job_id is None:
            if receipt is not None:
                raise ConflictError("Submission outcome is unknown; check the runtime's jobs before retrying")
            db.execute(
                "INSERT INTO trigger_receipts (idempotency_key, payload_hash) VALUES (?, ?)",
                (idempotency_key, payload_hash),
            )
            db.commit()
            try:
                native_job_id = create(name, payload["prompt"], payload["delivery_platform"])
            except (NotSubmittedError, RuntimeRejectedError):
                db.execute("DELETE FROM trigger_receipts WHERE idempotency_key = ?", (idempotency_key,))
                db.commit()
                raise
        db.execute(
            "INSERT INTO trigger_receipts (idempotency_key, payload_hash, native_job_id) VALUES (?, ?, ?) "
            "ON CONFLICT (idempotency_key) DO UPDATE SET native_job_id = excluded.native_job_id",
            (idempotency_key, payload_hash, native_job_id),
        )
        db.commit()
        return native_job_id


class TriggerHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/agent-triggers/v1/invocations":
            self._respond(404, {"error": "not found"})
            return
        authorization = self.headers.get("Authorization", "")
        if not TRIGGER_KEY or not hmac.compare_digest(authorization, f"Bearer {TRIGGER_KEY}"):
            self._respond(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._respond(413, {"error": "invalid body size"})
            return
        idempotency_key = self.headers.get("Idempotency-Key", "").strip()
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise TypeError("body must be an object")
            invocation_id = str(UUID(str(payload.get("invocation_id", ""))))
            generation = int(payload.get("dispatch_generation", 0))
            prompt = str(payload.get("prompt", "")).strip()
            platform = str(payload.get("delivery_platform", ""))
            if generation < 1 or not prompt or len(prompt) > 5_000 or platform not in PLATFORMS:
                raise ValueError("invalid trigger")
            expected_key = f"{invocation_id}:{generation}"
            if not idempotency_key or not hmac.compare_digest(idempotency_key, expected_key):
                raise ValueError("invalid idempotency key")
            native_job_id = dispatch(
                idempotency_key,
                {
                    "invocation_id": invocation_id,
                    "dispatch_generation": generation,
                    "prompt": prompt,
                    "delivery_platform": platform,
                },
            )
        except (TypeError, ValueError) as exc:
            self._respond(409 if isinstance(exc, ConflictError) else 400, {"error": str(exc)})
            return
        except DispatchError as exc:
            self._respond(503, {"error": str(exc)})
            return
        self._respond(202, {"native_job_id": native_job_id})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, status: int, body: dict) -> None:
        encoded = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), TriggerHandler).serve_forever()
