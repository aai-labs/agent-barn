"""Exercise the real pinned scheduler, replacing only the model execution."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = ["/opt/hermes", "/messaging"]
os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="agentbarn-cron-")
os.environ["AGENTBARN_SCHEDULED_DELIVERY"] = "1"
os.environ["AGENTBARN_MESSAGE_SPOOL"] = str(Path(os.environ["HERMES_HOME"]) / "messages.sqlite3")

from cron import scheduler  # ty: ignore[unresolved-import]
from cron.jobs import create_job  # ty: ignore[unresolved-import]


def run(text):
    job = create_job(prompt="Return the result", schedule="0 9 * * *", deliver="local")
    with patch.object(scheduler, "run_job", return_value=(True, "full output", text, None)):
        if not scheduler.run_one_job(job):
            raise AssertionError("Native scheduled execution did not complete")
    return job


run("Fresh completion without inbound history")
path = Path(os.environ["AGENTBARN_MESSAGE_SPOOL"])
if not path.exists():
    raise AssertionError("Pinned Hermes did not durably capture the scheduled completion")
# Every marker runtime_policy promises an agent will suppress delivery, and one
# report that merely quotes a marker mid-sentence, which must still deliver.
run("[SILENT]")
run("HEARTBEAT_OK")
run("SILENT")
run("Report mentioning [SILENT]")
deliverable = 2
with sqlite3.connect(path) as db:
    rows = db.execute("SELECT run_id, request, receipt FROM completions").fetchall()
if len(rows) != deliverable or len({row[0] for row in rows}) != deliverable:
    raise AssertionError(f"Expected {deliverable} distinct deliverable executions, got {len(rows)}")
if any(not row[0].startswith("hermes:") or row[2] is not None for row in rows):
    raise AssertionError("Completions must retain durable run identities until acknowledgement")
print("Hermes native completion capture and exact silence contract passed")
