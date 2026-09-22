"""Memory group CRUD + membership.

A memory group is a named memory pool: its id is the pool id, and the Agents in
it share the Honcho workspace `af-pool-<group id>`. Membership is the opt-in;
deleting a group drops every member (FK SET NULL) and deliberately erases the
shared pool.
"""

from unittest.mock import MagicMock
from uuid import uuid7

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.memory_groups.models import (
    MemoryGroup,
    MemoryGroupCreate,
    MemoryGroupUpdate,
    ShareMemoryItemCreate,
)
from api.domains.memory_groups.service import MemoryGroupService
from api.domains.rbac.catalog import PermissionKey


def _context(org_id):
    context = MagicMock()
    context.require_current_user_organization.return_value.organization_id = org_id
    context.user.id = uuid7()
    return context


def _service(*, honcho_enabled: bool = True):
    repository = MagicMock()
    permission_policy = MagicMock()
    honcho = MagicMock()
    agent_service = MagicMock()
    pool_memory = MagicMock()
    memory = MagicMock()
    service = MemoryGroupService(
        repository=repository,
        permission_policy=permission_policy,
        honcho=honcho,
        config=Config(honcho_enabled=honcho_enabled),
        agent_service=agent_service,
        pool_memory=pool_memory,
        memory=memory,
    )
    return service, repository, permission_policy, honcho, agent_service, pool_memory, memory


def test_create_group_requires_the_manage_permission_and_persists():
    org_id = uuid7()
    service, repository, permission_policy, _honcho, _agents, _pool, _mem = _service()

    service.create_group(MemoryGroupCreate(name="Research"), _context(org_id))

    # Gated on MEMORY_GROUP_MANAGE for this org.
    args = permission_policy.require_organization.call_args
    assert_that(args.args[1], equal_to(org_id))
    assert_that(args.args[2], equal_to(PermissionKey.MEMORY_GROUP_MANAGE))
    saved = repository.save.call_args.args[0]
    assert_that(saved.name, equal_to("Research"))
    assert_that(saved.organization_id, equal_to(org_id))


def test_add_agent_assigns_the_group_via_agent_service():
    org_id, agent_id = uuid7(), uuid7()
    service, repository, _pp, _honcho, agent_service, _pool, _mem = _service()
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.add_agent(group.id, agent_id, _context(org_id))

    agent_service.set_memory_group.assert_called_once_with(agent_id, group.id, org_id)


def test_remove_agent_clears_the_group():
    org_id, agent_id = uuid7(), uuid7()
    service, repository, _pp, _honcho, agent_service, _pool, _mem = _service()
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.remove_agent(group.id, agent_id, _context(org_id))

    agent_service.set_memory_group.assert_called_once_with(agent_id, None, org_id)


def test_delete_group_deliberately_purges_the_shared_pool():
    """Deleting a group is the one sanctioned path to erase a pool. The FK nulls
    members automatically; the pool workspace is purged via the deliberate method
    (the per-agent guard refuses pools)."""
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=True)
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.delete_group(group.id, _context(org_id))

    repository.delete.assert_called_once_with(group)
    honcho.delete_pool_workspace.assert_called_once_with(f"af-pool-{group.id}")


def test_delete_group_skips_pool_purge_when_memory_backend_is_off():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=False)
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.delete_group(group.id, _context(org_id))

    honcho.delete_pool_workspace.assert_not_called()


def test_rename_group_persists_the_new_name():
    org_id = uuid7()
    service, repository, _pp, _honcho, _agents, _pool, _mem = _service()
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Old")
    repository.get_by_id_and_org.return_value = group

    result = service.rename_group(group.id, MemoryGroupUpdate(name="New"), _context(org_id))

    assert_that(result.name, equal_to("New"))
    repository.save.assert_called_once_with(group)


def test_unauthorized_caller_cannot_manage_groups():
    org_id = uuid7()
    service, _repository, permission_policy, _honcho, _agents, _pool, _mem = _service()
    permission_policy.require_organization.side_effect = PermissionError("nope")

    with pytest.raises(PermissionError):
        service.create_group(MemoryGroupCreate(name="Research"), _context(org_id))


def _known_groups(org_id, *groups):
    """A get_by_id_and_org that resolves each of the given groups by id."""
    by_id = {g.id: g for g in groups}

    def resolve(group_id, _org_id):
        return by_id.get(group_id)

    return resolve


def test_share_item_copies_into_each_target_and_records_origin():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, pool_memory, _mem = _service(honcho_enabled=True)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    target_a = MemoryGroup(id=uuid7(), organization_id=org_id, name="Support")
    target_b = MemoryGroup(id=uuid7(), organization_id=org_id, name="Sales")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source, target_a, target_b)
    honcho.find_conclusion.return_value = {"id": "c1", "content": "The launch is in March."}
    honcho.share_fact.return_value = [{"id": "new1"}, {"id": "new2"}]

    payload = ShareMemoryItemCreate(memory_id="c1", target_group_ids=[target_a.id, target_b.id])
    result = service.share_item(source.id, payload, _context(org_id))

    # Read from the SOURCE pool, written into each TARGET pool with the fact's content.
    honcho.find_conclusion.assert_called_once_with(f"af-pool-{source.id}", "c1")
    written = {call.args[0] for call in honcho.share_fact.call_args_list}
    assert_that(written, equal_to({f"af-pool-{target_a.id}", f"af-pool-{target_b.id}"}))
    for call in honcho.share_fact.call_args_list:
        assert_that(call.args[2], equal_to("The launch is in March."))
    # Each target's copy is badged with the source group as its origin.
    origins = {
        call.kwargs["target_group_id"]: call.kwargs["source_group_id"]
        for call in pool_memory.record_share.call_args_list
    }
    assert_that(origins, equal_to({target_a.id: source.id, target_b.id: source.id}))
    assert_that([r.shared for r in result.results], equal_to([True, True]))


def test_share_item_rejects_sharing_a_group_with_itself():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=True)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source)

    payload = ShareMemoryItemCreate(memory_id="c1", target_group_ids=[source.id])
    with pytest.raises(HTTPException) as exc:
        service.share_item(source.id, payload, _context(org_id))

    assert_that(exc.value.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
    honcho.share_fact.assert_not_called()


def test_share_item_404_when_the_memory_is_not_in_the_source_pool():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=True)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    target = MemoryGroup(id=uuid7(), organization_id=org_id, name="Support")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source, target)
    honcho.find_conclusion.return_value = None

    payload = ShareMemoryItemCreate(memory_id="missing", target_group_ids=[target.id])
    with pytest.raises(HTTPException) as exc:
        service.share_item(source.id, payload, _context(org_id))

    assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    honcho.share_fact.assert_not_called()


def test_share_item_404_when_a_target_group_is_not_in_the_org():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=True)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source)  # target unknown

    payload = ShareMemoryItemCreate(memory_id="c1", target_group_ids=[uuid7()])
    with pytest.raises(HTTPException) as exc:
        service.share_item(source.id, payload, _context(org_id))

    assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    honcho.find_conclusion.assert_not_called()


def test_share_item_409_when_memory_backend_is_off():
    org_id = uuid7()
    service, repository, _pp, honcho, _agents, _pool, _mem = _service(honcho_enabled=False)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source)

    payload = ShareMemoryItemCreate(memory_id="c1", target_group_ids=[uuid7()])
    with pytest.raises(HTTPException) as exc:
        service.share_item(source.id, payload, _context(org_id))

    assert_that(exc.value.status_code, equal_to(status.HTTP_409_CONFLICT))
    honcho.share_fact.assert_not_called()


def test_share_item_reports_a_per_target_honcho_failure_without_failing_the_rest():
    from api.infrastructure.honcho.client import HonchoError

    org_id = uuid7()
    service, repository, _pp, honcho, _agents, pool_memory, _mem = _service(honcho_enabled=True)
    source = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    good = MemoryGroup(id=uuid7(), organization_id=org_id, name="Support")
    bad = MemoryGroup(id=uuid7(), organization_id=org_id, name="Sales")
    repository.get_by_id_and_org.side_effect = _known_groups(org_id, source, good, bad)
    honcho.find_conclusion.return_value = {"id": "c1", "content": "A fact."}

    def share(workspace, _peer, _content):
        if workspace == f"af-pool-{bad.id}":
            raise HonchoError("boom")
        return [{"id": "new1"}]

    honcho.share_fact.side_effect = share

    payload = ShareMemoryItemCreate(memory_id="c1", target_group_ids=[good.id, bad.id])
    result = service.share_item(source.id, payload, _context(org_id))

    outcomes = {r.group_id: r.shared for r in result.results}
    assert_that(outcomes, equal_to({good.id: True, bad.id: False}))
    # Provenance is recorded only for the target that actually took the write.
    recorded = {call.kwargs["target_group_id"] for call in pool_memory.record_share.call_args_list}
    assert_that(recorded, equal_to({good.id}))


def test_group_memory_list_resolves_the_pool_workspace_and_delegates():
    """Group memory is the pool's memory: it resolves the workspace straight from the
    group id and delegates to the workspace-keyed core — no member Agent involved."""
    org_id = uuid7()
    service, repository, _pp, _honcho, _agents, _pool, memory = _service(honcho_enabled=True)
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.list_memory(group.id, _context(org_id), page=1, size=50, observed=None)

    memory.list_memory_for_workspace.assert_called_once()
    assert_that(memory.list_memory_for_workspace.call_args.args[0], equal_to(f"af-pool-{group.id}"))


def test_group_memory_forget_delegates_to_the_pool_workspace():
    org_id = uuid7()
    service, repository, _pp, _honcho, _agents, _pool, memory = _service(honcho_enabled=True)
    group = MemoryGroup(id=uuid7(), organization_id=org_id, name="Research")
    repository.get_by_id_and_org.return_value = group

    service.forget_memory(group.id, "c1", _context(org_id))

    memory.forget_in_workspace.assert_called_once_with(f"af-pool-{group.id}", "c1")


def test_group_memory_404_for_a_group_not_in_the_org():
    org_id = uuid7()
    service, repository, _pp, _honcho, _agents, _pool, memory = _service(honcho_enabled=True)
    repository.get_by_id_and_org.return_value = None

    with pytest.raises(HTTPException) as exc:
        service.list_memory(uuid7(), _context(org_id), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))
    memory.list_memory_for_workspace.assert_not_called()


def test_group_memory_409_when_memory_backend_is_off():
    org_id = uuid7()
    service, _repository, _pp, _honcho, _agents, _pool, memory = _service(honcho_enabled=False)

    with pytest.raises(HTTPException) as exc:
        service.list_memory(uuid7(), _context(org_id), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(status.HTTP_409_CONFLICT))
    memory.list_memory_for_workspace.assert_not_called()
