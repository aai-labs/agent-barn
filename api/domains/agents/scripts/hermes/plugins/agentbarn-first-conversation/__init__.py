import json
import threading
from pathlib import Path

STATE_DIR = Path("/workspace/.agentbarn")
MAX_TURNS = 6
TOOLSET = "agentbarn-first-conversation"
TOOL_NAME = "finish_first_conversation"
BOOT_SESSION_ID = "agentbarn-boot"
UNATTENDED_PLATFORMS = frozenset({"cron", "curator", "subagent"})
WRAPPER = (
    "[Agent Barn — first conversation] This is the start of your first conversation with this "
    "person. Follow the script below across your next replies. If their message asks for real "
    "work, do that first and fit the script around it. Keep every message short. Don't mention "
    "this note, the script, or any file. When the script is complete, or the person declines it, "
    f"call `{TOOL_NAME}` once."
)
SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Call once when the first-conversation script is complete or the person declined it. "
        "Ends the script; it is not shown again."
    ),
    "parameters": {"type": "object", "properties": {}},
}

_lock = threading.Lock()


def _script() -> Path:
    return STATE_DIR / "BOOTSTRAP.md"


def _turns() -> Path:
    return STATE_DIR / "bootstrap-turns"


def _retire() -> None:
    _script().unlink(missing_ok=True)
    _turns().unlink(missing_ok=True)


def on_pre_llm_call(session_id="", platform="", parent_session_id="", **_):
    if platform in UNATTENDED_PLATFORMS or session_id == BOOT_SESSION_ID or parent_session_id:
        return None
    with _lock:
        script = _script()
        if not script.exists():
            return None
        turns_file = _turns()
        turns = int(turns_file.read_text(encoding="utf-8") or 0) + 1 if turns_file.exists() else 1
        if turns > MAX_TURNS:
            _retire()
            return None
        turns_file.write_text(str(turns), encoding="utf-8")
        return {"context": f"{WRAPPER}\n\n{script.read_text(encoding='utf-8')}"}


def finish_first_conversation(args, **_):
    with _lock:
        _retire()
    return json.dumps({"status": "done"})


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_tool(
        name=TOOL_NAME,
        toolset=TOOLSET,
        schema=SCHEMA,
        handler=finish_first_conversation,
        description=SCHEMA["description"],
    )
