"""AgentService.release_memory_group_members.

When a memory group is deleted, every member is detached and the running ones are
restarted so no live Agent keeps a token for the pool that is about to be erased
and writes back into it. AgentService has a large dependency graph, so these tests
bypass __init__ and drive the method against stubbed collaborators.
"""

from unittest.mock import MagicMock
from uuid import uuid7

from api.domains.agents.models import AgentStatus
from api.domains.agents.service import AgentService


def _service():
    service = AgentService.__new__(AgentService)
    service.repository = MagicMock()
    service.set_memory_group = MagicMock()
    service._stop_agent_unchecked = MagicMock(return_value="stopped-agent")
    service._start_agent_unchecked = MagicMock()
    # lifecycle_lock is a context manager that yields "acquired".
    service.repository.lifecycle_lock.return_value.__enter__.return_value = True
    return service


def test_release_detaches_every_member_and_restarts_only_the_running_ones():
    org_id = uuid7()
    group_id = uuid7()
    running = MagicMock(id=uuid7(), status=AgentStatus.RUNNING)
    stopped = MagicMock(id=uuid7(), status=AgentStatus.STOPPED)
    service = _service()
    service.repository.find_in_memory_group.return_value = [running, stopped]
    # Re-read inside the lifecycle lock confirms the running member is still running.
    service.repository.get_by_id.return_value = MagicMock(status=AgentStatus.RUNNING)

    service.release_memory_group_members(group_id, org_id)

    # Both members are opted out of the pool.
    assert service.set_memory_group.call_count == 2
    service.set_memory_group.assert_any_call(running.id, None, org_id)
    service.set_memory_group.assert_any_call(stopped.id, None, org_id)
    # Only the running member is restarted (to drop its live pool token).
    service._stop_agent_unchecked.assert_called_once()
    service._start_agent_unchecked.assert_called_once()


def test_release_is_best_effort_when_a_member_restart_fails():
    org_id = uuid7()
    group_id = uuid7()
    first = MagicMock(id=uuid7(), status=AgentStatus.RUNNING)
    second = MagicMock(id=uuid7(), status=AgentStatus.RUNNING)
    service = _service()
    service.repository.find_in_memory_group.return_value = [first, second]
    service.repository.get_by_id.return_value = MagicMock(status=AgentStatus.RUNNING)
    service._stop_agent_unchecked.side_effect = RuntimeError("k8s unavailable")

    # A restart failure is logged, not raised: the delete must still proceed.
    service.release_memory_group_members(group_id, org_id)

    # Membership is still cleared for both, and both restarts were attempted.
    assert service.set_memory_group.call_count == 2
    assert service._stop_agent_unchecked.call_count == 2
