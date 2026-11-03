"""Keep an Agent silent in listen-in rooms unless a message addresses it.

Hermes' free-response rooms answer every message. Each inbound message is
classified as it arrives, before Hermes' busy queue can hold it back, and a turn
takes its classification when it starts, so the decision belongs to the turn
rather than the session. A room turn that was never classified, such as one
resumed after a restart, counts as listening: a mistake means silence, not noise.

Unaddressed messages also lose gateway control, Hermes' own flag for untrusted
text, so they can't run slash commands or answer approval prompts.
"""

import logging
import os
import sys
import threading
from collections import OrderedDict, deque
from contextvars import ContextVar
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_MARKER = "NO_REPLY"
_MAX_TRACKED = 1_000
_REVIEW_THREAD = "bg-review"
_ROOM_SETTINGS = {
    "slack": "free_response_channels",
    "discord": "free_response_channels",
    "telegram": "free_response_chats",
}
_LISTENING = "listening"
_ADDRESSED = "addressed"
_REVIEW = "review"

_rooms: dict[str, set[str]] = {}
_queues: OrderedDict[str, deque[bool]] = OrderedDict()  # session_key -> oldest-first listening flags
_lock = threading.Lock()
_turn: ContextVar[str | None] = ContextVar("agentbarn_listen_in_turn", default=None)


def _load_rooms(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    config = yaml.safe_load(path.read_text()) or {}
    rooms = {}
    for platform, setting in _ROOM_SETTINGS.items():
        value = (config.get(platform) or {}).get(setting) or []
        ids = value if isinstance(value, list) else str(value).split(",")
        if found := {str(room).strip() for room in ids if str(room).strip()}:
            rooms[platform] = found
    return rooms


def _runner():
    from gateway.run import _gateway_runner_ref  # ty: ignore[unresolved-import]

    return _gateway_runner_ref()


def _session_env(name: str) -> str:
    from gateway.session_context import get_session_env  # ty: ignore[unresolved-import]

    return get_session_env(name, "")


def _is_known_command(name: str | None) -> bool:
    from hermes_cli.commands import is_gateway_known_command  # ty: ignore[unresolved-import]

    return is_gateway_known_command(name)


def _is_room(source) -> bool:
    rooms = _rooms.get(str(getattr(source.platform, "value", source.platform)), set())
    return str(source.chat_id) in rooms or str(getattr(source, "parent_chat_id", None)) in rooms


def _slack_addressed(adapter, raw: dict) -> bool:
    team = raw.get("team")
    bot = adapter._team_bot_user_ids.get(team, adapter._bot_user_id)
    detect = sys.modules[type(adapter).__module__]._slack_mention_detection_text
    text = detect(raw) or raw.get("text") or ""
    if (bot and f"<@{bot}>" in text) or adapter._slack_message_matches_mention_patterns(text):
        return True
    thread = raw.get("thread_ts")
    if not thread or thread == raw.get("ts") or adapter._slack_thread_require_mention():
        return False
    owned = adapter._bot_message_ts | adapter._mentioned_threads
    return thread in owned or adapter._workspace_message_marker(team, thread) in owned


def _discord_addressed(adapter, raw) -> bool:
    if type(raw).__name__ == "Interaction":
        return True
    if adapter._self_is_explicitly_mentioned(raw):
        return True
    own_roles = {role.id for role in getattr(getattr(getattr(raw, "guild", None), "me", None), "roles", [])}
    return bool(own_roles & {role.id for role in getattr(raw, "role_mentions", [])})


def _telegram_addressed(adapter, raw) -> bool:
    return (
        adapter._message_mentions_bot(raw)
        or adapter._is_reply_to_bot(raw)
        or adapter._message_matches_mention_patterns(raw)
    )


_ADDRESSED_BY_PLATFORM = {
    "slack": _slack_addressed,
    "discord": _discord_addressed,
    "telegram": _telegram_addressed,
}


def _is_addressed(adapter, event) -> bool:
    if event.reply_to_is_own_message:
        return True
    platform = str(getattr(event.source.platform, "value", event.source.platform))
    try:
        return bool(_ADDRESSED_BY_PLATFORM[platform](adapter, event.raw_message))
    except Exception:
        logger.exception("agentbarn-listen-in could not classify a %s message", platform)
        return False


def _classify(adapter, event) -> None:
    if event.internal or not _is_room(event.source):
        return
    addressed = _is_addressed(adapter, event)
    if not addressed:
        event.allow_gateway_control = False
    elif event.is_command() and _is_known_command(event.get_command()):
        return
    key = _runner()._session_key_for_source(event.source)
    with _lock:
        _queues.setdefault(key, deque()).append(not addressed)
        _queues.move_to_end(key)
        if len(_queues) > _MAX_TRACKED:
            _queues.popitem(last=False)


def _in_room_session() -> bool:
    if _session_env("HERMES_CRON_SESSION") == "1":
        return False
    if _session_env("HERMES_SESSION_KEY") in _queues:
        return True
    chat_id = _session_env("HERMES_SESSION_CHAT_ID")
    return any(chat_id in rooms for rooms in _rooms.values())


def _on_pre_llm_call(**_):
    if threading.current_thread().name == _REVIEW_THREAD:
        _turn.set(_REVIEW)
        return
    if not _in_room_session():
        _turn.set(None)
        return
    with _lock:
        queue = _queues.get(_session_env("HERMES_SESSION_KEY"))
        listening = queue.popleft() if queue else True
    _turn.set(_LISTENING if listening else _ADDRESSED)


def _on_transform(response_text=None, **_):
    turn = _turn.get()
    if turn == _REVIEW:
        return None
    if turn == _LISTENING or (turn is None and _in_room_session()):
        return _MARKER
    if turn != _ADDRESSED:
        return None
    stripped = (response_text or "").strip()
    if stripped.endswith(_MARKER) and (clean := stripped[: -len(_MARKER)].rstrip()):
        return clean
    return None


def _patch_ingress(adapter_class) -> None:
    original = adapter_class.handle_message

    async def handle_message(self, event):
        try:
            _classify(self, event)
        except Exception:
            logger.exception("agentbarn-listen-in classification failed")
        return await original(self, event)

    adapter_class.handle_message = handle_message


def _install_ingress() -> None:
    from gateway.platforms.base import BasePlatformAdapter  # ty: ignore[unresolved-import]

    _patch_ingress(BasePlatformAdapter)


def register(ctx):
    rooms = _load_rooms(Path(os.environ.get("HERMES_HOME", "/opt/data")) / "config.yaml")
    if not rooms:
        return
    _rooms.clear()
    _rooms.update(rooms)
    _install_ingress()
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("transform_llm_output", _on_transform)
