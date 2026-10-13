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
CLOSE_NOTE = (
    "[Agent Barn — first conversation] The first-conversation script is complete. Ignore the "
    "earlier first-conversation note and script in this chat and reply normally."
)
FINISHED = {
    "status": "done",
    "next": "Nothing from this turn has reached the person yet. Now write your complete reply to them.",
}
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


def _sessions() -> Path:
    return STATE_DIR / "bootstrap-sessions"


def _closing() -> Path:
    return STATE_DIR / "bootstrap-closing"


def _read_ids(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _write_ids(path: Path, ids: list[str]) -> None:
    if ids:
        path.write_text(json.dumps(ids), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _retire() -> None:
    closing = _read_ids(_closing())
    closing += [session for session in _read_ids(_sessions()) if session not in closing]
    _write_ids(_closing(), closing)
    _sessions().unlink(missing_ok=True)
    _script().unlink(missing_ok=True)
    _turns().unlink(missing_ok=True)


def on_pre_llm_call(session_id="", platform="", parent_session_id="", **_):
    if platform in UNATTENDED_PLATFORMS or session_id == BOOT_SESSION_ID or parent_session_id:
        return None
    with _lock:
        script = _script()
        if script.exists():
            turns_file = _turns()
            turns = int(turns_file.read_text(encoding="utf-8") or 0) + 1 if turns_file.exists() else 1
            if turns > MAX_TURNS:
                _retire()
            else:
                turns_file.write_text(str(turns), encoding="utf-8")
        closing = _read_ids(_closing())
        if session_id in closing:
            closing.remove(session_id)
            _write_ids(_closing(), closing)
            return {"context": CLOSE_NOTE}
        if not script.exists():
            return None
        sessions = _read_ids(_sessions())
        if session_id in sessions:
            return None
        _write_ids(_sessions(), [*sessions, session_id])
        return {"context": f"{WRAPPER}\n\n{script.read_text(encoding='utf-8')}"}


def finish_first_conversation(args, **_):
    with _lock:
        _retire()
    return json.dumps(FINISHED)


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_tool(
        name=TOOL_NAME,
        toolset=TOOLSET,
        schema=SCHEMA,
        handler=finish_first_conversation,
        description=SCHEMA["description"],
    )
