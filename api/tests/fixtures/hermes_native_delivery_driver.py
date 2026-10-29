"""Exercise pinned Hermes native cron delivery, replacing model/provider traffic only."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="native-cron-")
os.environ["SLACK_BOT_TOKEN"] = "test-token"
os.environ["SLACK_APP_TOKEN"] = "test-app-token"
os.environ["SLACK_HOME_CHANNEL"] = "C_HOME"

from cron import scheduler  # ty: ignore[unresolved-import]
from cron.jobs import create_job, load_jobs  # ty: ignore[unresolved-import]

# The native send engine serves cron/CLI, but is not an agent-callable tool.
from tools.registry import registry  # ty: ignore[unresolved-import]

assert registry.get_entry("send_message") is None

sent = []


async def send(platform, config, chat_id, content, **kwargs):
    sent.append((platform.value, chat_id, kwargs.get("thread_id"), content))
    return {"ok": True}


for name, origin, deliver, target in [
    ("origin", {"platform": "slack", "chat_id": "C_ORIGIN", "thread_id": "123"}, "origin", ("C_ORIGIN", "123")),
    ("webhook", None, "slack", ("C_HOME", None)),
]:
    job = create_job(prompt="Native scheduled result", schedule="0 9 * * *", name=name, origin=origin, deliver=deliver)
    before = len(sent)
    with (
        patch.object(scheduler, "run_job", return_value=(True, "saved output", "Native result", None)),
        patch.object(scheduler, "_preflight_job_config", return_value=None),
        patch("tools.send_message_tool._send_to_platform", side_effect=send),
    ):
        assert scheduler.run_one_job(job)
    assert len(sent) == before + 1, sent
    assert sent[-1][0:3] == ("slack", *target), sent
    assert "Native result" in sent[-1][3]
    assert any(row["id"] == job["id"] for row in load_jobs())

silent = create_job(prompt="No update", schedule="0 9 * * *", deliver="slack")
with (
    patch.object(scheduler, "run_job", return_value=(True, "saved output", "[SILENT]", None)),
    patch.object(scheduler, "_preflight_job_config", return_value=None),
    patch("tools.send_message_tool._send_to_platform", side_effect=send),
):
    assert scheduler.run_one_job(silent)
assert len(sent) == 2, sent
assert not (Path(os.environ["HERMES_HOME"]) / "agentbarn-messages.sqlite3").exists()
assert "agentbarn_message" not in __import__("inspect").getsource(scheduler.run_one_job)
print("Hermes native origin/home delivery once, silence, saved job state, and no bridge passed")
