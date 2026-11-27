"""Run Agent Barn's session-prune.py against state.db files the pinned Hermes wrote.

Runs inside a Hermes image with the script mounted at /session-prune.py. In the Parent
Agent's home it seeds ended cron sessions spread over 30 days, a cron session still
running, a pinned old cron session and an ended API session past every retention; in a
Bot profile, one old and one recent ended cron session. Then it prunes once. Prints JSON:
which sessions survived in each, how many sessions the largest single prune_sessions call
deleted, and whether the search index kept up.
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
BOT_HOME = HOME / "profiles" / "bot-1"
os.environ["HERMES_HOME"] = str(HOME)
os.chdir("/opt/hermes")
sys.path.insert(0, "/opt/hermes")

import hermes_state  # ty: ignore[unresolved-import]

DAY = 86400
DAYS = 30
PER_DAY = 4


def _seed(db_path: Path, ages: dict[str, float], open_ids: tuple[str, ...] = (), pinned: tuple[str, ...] = ()) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = hermes_state.SessionDB(db_path)
    for sid in ages:
        db.create_session(sid, "api_server" if sid.startswith("api") else "cron")
        db.append_message(sid, "assistant", content=f"report from {sid}")
        if sid not in open_ids:
            db.end_session(sid, "done")
    db.close()
    now = time.time()
    conn = sqlite3.connect(db_path)
    for sid, age in ages.items():
        at = now - age * DAY
        ended = None if sid in open_ids else at
        conn.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?", (at, ended, sid))
        conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = ?", (at, sid))
    conn.executemany("UPDATE sessions SET pinned = 1 WHERE id = ?", [(sid,) for sid in pinned])
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
    module._run()
    return max(deleted_per_call, default=0)


def _remaining(db_path: Path) -> tuple[set[str], bool]:
    conn = sqlite3.connect(db_path)
    ids = {row[0] for row in conn.execute("SELECT id FROM sessions")}
    in_sync = (
        conn.execute("SELECT count(*) FROM messages_fts").fetchone()
        == conn.execute("SELECT count(*) FROM messages").fetchone()
    )
    conn.close()
    return ids, in_sync


def main() -> None:
    # Session cron_<d>_<n> was last active d and a half days ago.
    parent = {f"cron_{day}_{n}": day + 0.5 for day in range(DAYS) for n in range(PER_DAY)}
    parent.update({"cron_running": 60, "cron_pinned": 60, "api_old": 60})
    _seed(HOME / "state.db", parent, open_ids=("cron_running",), pinned=("cron_pinned",))
    _seed(BOT_HOME / "state.db", {"bot_cron_old": 20, "bot_cron_new": 2})

    largest_call = _prune()

    remaining, parent_in_sync = _remaining(HOME / "state.db")
    bot_remaining, bot_in_sync = _remaining(BOT_HOME / "state.db")
    kept_days = sorted({int(sid.split("_")[1]) for sid in remaining if sid.split("_")[1].isdigit()})
    print(
        json.dumps(
            {
                "kept_cron_days": kept_days,
                "running_cron_kept": "cron_running" in remaining,
                "pinned_cron_kept": "cron_pinned" in remaining,
                "old_api_session_kept": "api_old" in remaining,
                "bot_sessions_kept": sorted(bot_remaining),
                "largest_single_prune": largest_call,
                "index_matches_messages": parent_in_sync and bot_in_sync,
            }
        )
    )


if __name__ == "__main__":
    main()
