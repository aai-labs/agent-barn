"""Which Honcho requests an Agent may send through the memory proxy.

The proxy forwards with a token scoped to the Agent's own pool, so Honcho already
refuses every other workspace. These rules cover what that scope still allows: an
Agent must not set configuration anywhere in its pool (Honcho resolves it message,
then session, then workspace, so a session's can override our deriver instructions
or turn dreams on), delete the pool, or start model work no runtime asks for.
"""

from typing import Any


class MemoryRequestRefused(Exception):
    """A request the Agent's rights do not cover. The message is safe to return."""


# Workspace-level operations an Agent never needs.
_REFUSED_POOL_ACTIONS = frozenset({"schedule_dream"})


def check_memory_request(method: str, path: str, body: Any, workspace: str) -> None:
    """Raise `MemoryRequestRefused` unless `method path` is allowed for `workspace`.

    `path` is relative to Honcho's root (e.g. `v3/workspaces/<ws>/chat`) and `body`
    is the parsed JSON body, or None when there is none.
    """
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise MemoryRequestRefused("Malformed path")
    if segments[:2] != ["v3", "workspaces"]:
        raise MemoryRequestRefused("Not a memory path")

    _refuse_configuration(body)
    rest = segments[2:]
    if not rest:
        # Get-or-create. Only the Agent's own pool, and never with a configuration.
        if method != "POST" or not isinstance(body, dict) or body.get("id") != workspace:
            raise MemoryRequestRefused("Only the agent's own memory pool is reachable")
        return
    if rest[0] != workspace:
        raise MemoryRequestRefused("Only the agent's own memory pool is reachable")

    if len(rest) == 1:
        if method == "DELETE":
            raise MemoryRequestRefused("A memory pool is removed with its group")
        if method in ("PUT", "PATCH") and not isinstance(body, dict):
            raise MemoryRequestRefused("Unreadable workspace update")
        return
    if rest[1] in _REFUSED_POOL_ACTIONS:
        raise MemoryRequestRefused("Not available to agents")


def _refuse_configuration(body: Any) -> None:
    """Configuration on the body itself, or on any message in a batch. Neither
    runtime sends any; metadata is left alone, since it is free-form data."""
    if not isinstance(body, dict):
        return
    messages = body.get("messages")
    items = [body, *(m for m in messages if isinstance(m, dict))] if isinstance(messages, list) else [body]
    if any("configuration" in item for item in items):
        raise MemoryRequestRefused("Memory configuration is managed by the platform")
