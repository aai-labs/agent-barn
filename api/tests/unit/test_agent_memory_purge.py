"""Deleting an Agent erases what it learned.

Deletion already destroys the volume, the secret, and every other trace, and there
is no restore path anywhere. Retaining derived conclusions about real people —
owned by an Agent nobody owns, under no retention policy — would be the odd
exception rather than a safeguard. Anything worth keeping is copied out first
through the carry-over the delete flow offers.

Why a handler and not `delete_agent`: Honcho refuses a workspace delete while any
session remains, and processes both the session and workspace deletes
asynchronously, so the purge can lose that race. Under the delivery framework a
lost race is retried; inline it would have been a log line and memory left behind.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.agents.event_handlers import AgentMemoryPurgeHandler
from api.domains.events.handlers import RetryableEventHandlerError
from api.infrastructure.honcho.client import HonchoClient, HonchoError


def _event(agent_id):
    return MagicMock(payload={"agent_id": str(agent_id)})


def test_purges_the_deleted_agents_workspace():
    honcho = MagicMock()
    handler = AgentMemoryPurgeHandler(honcho=honcho, config=Config(honcho_enabled=True))
    agent_id = uuid7()

    handler.handle(_event(agent_id), MagicMock())

    honcho.delete_workspace.assert_called_once_with(f"af-{agent_id}")


def test_a_failed_purge_is_retryable_rather_than_dropped():
    """The usual cause is Honcho still clearing sessions. Treating it as terminal
    would leave a deleted Agent's memory in place with nothing in the product able
    to reach it — there is no view onto a deleted Agent any more."""
    honcho = MagicMock()
    honcho.delete_workspace.side_effect = HonchoError("active session(s) remain")
    handler = AgentMemoryPurgeHandler(honcho=honcho, config=Config(honcho_enabled=True))

    with pytest.raises(RetryableEventHandlerError):
        handler.handle(_event(uuid7()), MagicMock())


def test_nothing_is_erased_when_the_memory_backend_is_off():
    """No workspace was ever created, and the call would go to a service that may
    not be deployed at all."""
    honcho = MagicMock()
    handler = AgentMemoryPurgeHandler(honcho=honcho, config=Config(honcho_enabled=False))

    handler.handle(_event(uuid7()), MagicMock())

    honcho.delete_workspace.assert_not_called()


def test_delete_workspace_refuses_a_shared_pool():
    """A pool workspace is shared by every opted-in Agent in it. Deleting one Agent
    must never be able to erase it — so the purge path itself refuses a pool id,
    a structural guard rather than a promise the caller passes the right name."""
    client = HonchoClient(config=Config(honcho_base_url="http://honcho"))
    with (
        patch.object(HonchoClient, "list_sessions") as list_sessions,
        patch.object(HonchoClient, "_request") as request,
        pytest.raises(HonchoError),
    ):
        client.delete_workspace("af-pool-11111111-2222-3333-4444-555555555555")
    # It must refuse before touching anything.
    list_sessions.assert_not_called()
    request.assert_not_called()


def test_delete_pool_workspace_deliberately_erases_a_pool():
    """Group deletion erases the shared pool through the deliberate method, which
    is NOT blocked by the guard that stops the per-Agent purge from touching a
    pool. Sessions still go first."""
    client = HonchoClient(config=Config(honcho_base_url="http://honcho"))
    calls: list[str] = []

    with (
        patch.object(HonchoClient, "list_sessions", return_value=["s1"]),
        patch.object(HonchoClient, "delete_session", side_effect=lambda w, s: calls.append(f"session:{s}")),
        patch.object(HonchoClient, "_request", side_effect=lambda m, path, **kw: calls.append(f"{m}:{path}")),
    ):
        client.delete_pool_workspace("af-pool-11111111-2222-3333-4444-555555555555")

    assert_that(
        calls,
        equal_to(["session:s1", "DELETE:/workspaces/af-pool-11111111-2222-3333-4444-555555555555"]),
    )


def test_sessions_are_deleted_before_the_workspace():
    """Honcho returns 409 on a workspace delete while any session remains, which is
    the normal state for an Agent that did any work — confirmed against a live
    workspace, so the ordering is load-bearing rather than defensive."""
    client = HonchoClient(config=Config(honcho_base_url="http://honcho"))
    calls: list[str] = []

    with (
        patch.object(HonchoClient, "list_sessions", return_value=["s1", "s2"]),
        patch.object(HonchoClient, "delete_session", side_effect=lambda w, s: calls.append(f"session:{s}")),
        patch.object(HonchoClient, "_request", side_effect=lambda m, path, **kw: calls.append(f"{m}:{path}")),
    ):
        client.delete_workspace("af-x")

    assert_that(calls, equal_to(["session:s1", "session:s2", "DELETE:/workspaces/af-x"]))
