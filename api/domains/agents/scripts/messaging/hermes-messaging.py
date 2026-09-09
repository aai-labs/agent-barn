"""Hermes tool middleware binds message CLI calls to the actual inbound session."""

import shlex

from agentbarn_message import execution_environment


def before_tool(tool_name=None, args=None, session_id=None, tool_call_id=None, **kwargs):
    if tool_name != "terminal" or not isinstance(args, dict):
        return None
    command = args.get("command", "")
    if "agentbarn-message" not in command:
        return None
    try:
        # Validate the binding now; only non-secret correlation IDs enter tool audit.
        execution_environment(session_id, tool_call_id)
    except (ValueError, OSError):
        return {
            "action": "block",
            "message": "Explicit messaging requires an active inbound execution. "
            "Scheduled results are delivered automatically to the configured default.",
        }
    assert isinstance(session_id, str) and isinstance(tool_call_id, str)
    prefix = f"AGENTBARN_TOOL_SESSION={shlex.quote(session_id)} AGENTBARN_TOOL_INVOCATION={shlex.quote(tool_call_id)} "
    return {"action": "modify", "args": {"command": prefix + "sh -c " + shlex.quote(command)}}


def register(ctx):
    ctx.register_hook("pre_tool_call", before_tool)
