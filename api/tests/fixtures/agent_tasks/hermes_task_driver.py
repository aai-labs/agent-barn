"""Run the Task command through the pinned Hermes terminal tool, as the Agent would."""

import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/hermes")

import yaml
from hermes_cli.plugins import discover_plugins, get_plugin_manager  # ty: ignore[unresolved-import]
from hermes_cli.tools_config import _get_platform_tools  # ty: ignore[unresolved-import]
from model_tools import get_tool_definitions, handle_function_call  # ty: ignore[unresolved-import]
from tools.terminal_tool import terminal_tool  # ty: ignore[unresolved-import]
from tools.tool_search import load_config as load_tool_search_config  # ty: ignore[unresolved-import]

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

# The agentbarn-tasks plugin, loaded the way the gateway loads it.
discover_plugins(force=True)
manager = get_plugin_manager()
config = yaml.safe_load(Path("/opt/data/config.yaml").read_text())
# Whether each platform enables the plugin's toolset, as the gateway resolves it, and whether that
# toolset yields the tool. Building every toolset's definitions starts browsers and MCP servers.
offered = {
    platform: "agentbarn" in _get_platform_tools(config, platform, include_default_mcp_servers=False)
    for platform in ("slack", "api_server")
}
definitions = get_tool_definitions(enabled_toolsets=["agentbarn"], quiet_mode=True, skip_tool_search_assembly=True)
plugin = {
    "hooks": sorted(
        hook
        for hook in ("pre_llm_call", "post_tool_call", "transform_tool_result", "on_session_end", "pre_verify")
        if manager.has_hook(hook)
    ),
    "offered": offered,
    "tool_search": load_tool_search_config().enabled,
    "tools": sorted(definition["function"]["name"] for definition in definitions),
    "tool_result": json.loads(
        handle_function_call("agentbarn_task", {"action": "create", "title": "From the plugin"}, task_id="contract")
    ),
}

print(
    "TASK_RUNTIME_CONTRACT="
    + json.dumps({"results": results, "plugin": plugin, "instructions": Path("/workspace/AGENTS.md").read_text()})
)
