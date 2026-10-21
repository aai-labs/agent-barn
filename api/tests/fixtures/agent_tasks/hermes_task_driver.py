"""Run the Task command through the pinned Hermes terminal tool, as the Agent would."""

import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/hermes")

from tools.terminal_tool import terminal_tool  # ty: ignore[unresolved-import]

TASK_ID = sys.argv[1]
COMMANDS = {
    "discover": "command -v agentbarn-task",
    "create": 'agentbarn-task create --title "Reconcile invoices" --description "For October"',
    "status": f"agentbarn-task status {TASK_ID} in_progress",
    "note": f"agentbarn-task note {TASK_ID} <<'NOTE'\nMatched 40 of 42 invoices\nNOTE",
    "attach": f"printf 'invoice,amount\\n1,10\\n' > report.csv && agentbarn-task attach {TASK_ID} report.csv",
    "refused": f"printf 'x' > too-big.csv && agentbarn-task attach {TASK_ID} too-big.csv",
    "list": "agentbarn-task list --status open",
    "show": f"agentbarn-task show {TASK_ID}",
}

results = {}
for name, command in COMMANDS.items():
    call = json.loads(terminal_tool(command=command, timeout=30))
    results[name] = {"exit_code": call.get("exit_code"), "output": call.get("output", "")}

print(
    "TASK_RUNTIME_CONTRACT="
    + json.dumps({"results": results, "instructions": Path("/workspace/AGENTS.md").read_text()})
)
