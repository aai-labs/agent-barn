"""Which Honcho requests an Agent may send through the memory proxy.

The proxy forwards with a token scoped to the Agent's own pool, so Honcho already
refuses every other workspace. These rules cover what that scope still allows: an
Agent must not rewrite its pool's configuration (our deriver instructions live
there), delete the pool, or start model work no runtime asks for.
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

    rest = segments[2:]
    if not rest:
        # Get-or-create. Only the Agent's own pool, and never with a configuration.
        if method != "POST" or not isinstance(body, dict) or body.get("id") != workspace:
            raise MemoryRequestRefused("Only the agent's own memory pool is reachable")
        _refuse_configuration(body)
        return
    if rest[0] != workspace:
        raise MemoryRequestRefused("Only the agent's own memory pool is reachable")

    if len(rest) == 1:
        if method == "DELETE":
            raise MemoryRequestRefused("A memory pool is removed with its group")
        if method in ("PUT", "PATCH"):
            if not isinstance(body, dict):
                raise MemoryRequestRefused("Unreadable workspace update")
            _refuse_configuration(body)
        return
    if rest[1] in _REFUSED_POOL_ACTIONS:
        raise MemoryRequestRefused("Not available to agents")


def _refuse_configuration(body: dict) -> None:
    if "configuration" in body:
        raise MemoryRequestRefused("A memory pool's configuration is managed by the platform")
