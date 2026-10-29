"""Stands in for agentbarn-task: records each call, answers like the real command.

Calls are appended to $FAKE_TASK_LOG as JSON lines. `list` answers with $FAKE_TASK_LIST
(a JSON list of Tasks, filtered by --status), fails when $FAKE_TASK_LIST_FAIL is set, and
waits $FAKE_TASK_LIST_SLEEP seconds first; a value of "fail" makes any call fail.
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.environ["FAKE_TASK_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin, "cwd": os.getcwd()}) + "\n")

options = dict(arg[2:].split("=", 1) for arg in argv if arg.startswith("--") and "=" in arg)
if "fail" in argv or "fail" in options.values():
    print("The request was refused: the title is not allowed", file=sys.stderr)
    raise SystemExit(1)
if argv[0] == "list":
    time.sleep(float(os.environ.get("FAKE_TASK_LIST_SLEEP", "0")))
    if os.environ.get("FAKE_TASK_LIST_FAIL"):
        print("Agent Barn Tasks are unavailable right now.", file=sys.stderr)
        raise SystemExit(1)
    tasks = json.loads(os.environ.get("FAKE_TASK_LIST", "[]"))
    status = options.get("status")
    items = [task for task in tasks if status is None or task["status"] == status]
    print(json.dumps({"items": items, "total": len(items), "page": 1, "page_size": 25}))
else:
    print(json.dumps({"id": "0199f1d2-0000-7000-8000-0000000000aa", "status": "open"}))
