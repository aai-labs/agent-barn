"""Report whether Hermes keeps its lock on state.db when an observer poll overlaps a SessionDB().

Runs inside a Hermes image with Agent Barn's observer plugin mounted at /plugin.py. While the
observer's state.db query runs, the gateway opens a SessionDB() in the same process, as it does
when a turn or cron run starts during a poll. Prints JSON: whether the overlap happened, how many
replies the poll mirrored, and how many POSIX locks the process holds on state.db afterwards.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HERMES_HOME"] = str(HOME)
os.chdir("/opt/hermes")
sys.path.insert(0, "/opt/hermes")

import hermes_state  # ty: ignore[unresolved-import]

DB = HOME / "state.db"


def _locks_held_on(path: Path) -> int:
    inode = f":{path.stat().st_ino}"
    me = str(os.getpid())
    with open("/proc/locks") as table:
        return sum(1 for line in table if line.split()[4] == me and line.split()[5].endswith(inode))


def _load_plugin():
    spec = importlib.util.spec_from_file_location("agentbarn_observer", "/plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state_db_has_a_delivered_reply() -> None:
    db = hermes_state.SessionDB(db_path=DB)
    db._conn.execute(
        "CREATE TABLE IF NOT EXISTS delivery_obligations (obligation_id TEXT PRIMARY KEY, session_key TEXT,"
        " platform TEXT, chat_id TEXT, thread_id TEXT, content TEXT, state TEXT, updated_at REAL)"
    )
    db._conn.execute(
        "INSERT INTO delivery_obligations VALUES ('reply-1', 'agent:main:slack:group:C1', 'slack', 'C1', 'T1',"
        " 'a reply', 'delivered', 1.0)"
    )
    db._conn.commit()
    db.close()


overlap = {"armed": False, "turn": None}


def _start_a_turn_during_the_observer_query(sql: str) -> None:
    if overlap["armed"] and "delivery_obligations" in sql:
        overlap["armed"] = False
        overlap["turn"] = hermes_state.SessionDB(db_path=DB)


_real_connect = sqlite3.connect


def _connect_watching_the_observer_query(*args, **kwargs):
    conn = _real_connect(*args, **kwargs)
    if overlap["armed"]:
        conn.set_trace_callback(_start_a_turn_during_the_observer_query)
    return conn


_state_db_has_a_delivered_reply()
plugin = _load_plugin()
# Hermes's connect_tracked looks sqlite3.connect up at call time, so this sees the observer's
# connection however the plugin opens it.
sqlite3.connect = _connect_watching_the_observer_query  # ty: ignore[invalid-assignment]

overlap["armed"] = True
plugin.poll_obligations(DB, [0.0])
overlap["armed"] = False

turn = overlap["turn"]
if turn is not None:
    turn._conn.execute("SELECT count(*) FROM sessions").fetchall()

print(
    json.dumps(
        {
            "overlapped": turn is not None,
            "mirrored": len(plugin._messages),
            "locks_held_on_state_db": _locks_held_on(DB),
        }
    )
)
