"""Stands in for agentbarn-task: records each call, answers like the real command.

Calls are appended to $FAKE_TASK_LOG as JSON lines. `list` answers with $FAKE_TASK_LIST
(a JSON list of Tasks, filtered by --status); a Task title of "fail" makes the call fail.
"""

import json
import os
import sys

argv = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.environ["FAKE_TASK_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin, "cwd": os.getcwd()}) + "\n")

if "fail" in argv:
    print("The request was refused: the title is not allowed", file=sys.stderr)
    raise SystemExit(1)
if argv[0] == "list":
    tasks = json.loads(os.environ.get("FAKE_TASK_LIST", "[]"))
    status = argv[argv.index("--status") + 1] if "--status" in argv else None
    items = [task for task in tasks if status is None or task["status"] == status]
    print(json.dumps({"items": items, "total": len(items), "page": 1, "page_size": 25}))
else:
    print(json.dumps({"id": "0199f1d2-0000-7000-8000-0000000000aa", "status": "open"}))
