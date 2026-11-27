"""Run Agent Barn's session-prune.py against a state.db the pinned Hermes wrote.

Runs inside a Hermes image with the script mounted at /session-prune.py. Seeds ended cron
sessions spread over 30 days, a cron session still running, and an ended API session past
every retention, then prunes once. Prints JSON: which sessions survived, how many sessions
the largest single prune_sessions call deleted, and whether the search index kept up.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HERMES_HOME"] = str(HOME)
os.chdir("/opt/hermes")
sys.path.insert(0, "/opt/hermes")

import hermes_state  # ty: ignore[unresolved-import]

DAY = 86400
DAYS = 30
PER_DAY = 4
DB = HOME / "state.db"


def _seed() -> None:
    db = hermes_state.SessionDB(DB)
    ids = [f"cron_{day}_{n}" for day in range(DAYS) for n in range(PER_DAY)]
    for sid in [*ids, "cron_running", "api_old"]:
        db.create_session(sid, "api_server" if sid == "api_old" else "cron")
        db.append_message(sid, "assistant", content=f"report from {sid}")
        if sid != "cron_running":
            db.end_session(sid, "done")
    db.close()
    now = time.time()
    conn = sqlite3.connect(DB)
    # Session cron_<d>_<n> was last active d and a half days ago.
    for sid in ids:
        at = now - (int(sid.split("_")[1]) + 0.5) * DAY
        conn.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?", (at, at, sid))
        conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = ?", (at, sid))
    for sid in ("cron_running", "api_old"):
        at = now - 60 * DAY
        conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (at, sid))
        conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = ?", (at, sid))
    conn.commit()
    conn.close()


def _prune() -> int:
    spec = importlib.util.spec_from_file_location("session_prune", "/session-prune.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    deleted_per_call: list[int] = []
    original = hermes_state.SessionDB.prune_sessions

    def counting(self, *args, **kwargs):
        deleted = original(self, *args, **kwargs)
        deleted_per_call.append(deleted)
        return deleted

    hermes_state.SessionDB.prune_sessions = counting
    db = hermes_state.SessionDB(DB)
    try:
        module.prune_once(db)
    finally:
        db.close()
    return max(deleted_per_call, default=0)


def main() -> None:
    _seed()
    largest_call = _prune()
    conn = sqlite3.connect(DB)
    remaining = {row[0] for row in conn.execute("SELECT id FROM sessions")}
    indexed = conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0]
    messages = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
    conn.close()
    kept_days = sorted({int(sid.split("_")[1]) for sid in remaining if sid.split("_")[1].isdigit()})
    print(
        json.dumps(
            {
                "kept_cron_days": kept_days,
                "running_cron_kept": "cron_running" in remaining,
                "old_api_session_kept": "api_old" in remaining,
                "largest_single_prune": largest_call,
                "index_matches_messages": indexed == messages,
            }
        )
    )


if __name__ == "__main__":
    main()
