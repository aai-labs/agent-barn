"""Per-group memory cost on the org cost surface.

The apportionment lives in HonchoUsageService.cost_by_group (tested separately);
this covers the CostService layer: scoping the split to the caller's org, labelling
each group, defaulting groups with no activity to 0, and ranking by cost.
"""

from unittest.mock import MagicMock
from uuid import uuid7

from hamcrest import assert_that, contains_exactly, equal_to

from api.domains.costs.service import CostService


def _context(org_id):
    context = MagicMock()
    context.require_current_user_organization.return_value.organization_id = org_id
    return context


def _service(cost_by_group: dict[str, float], names: dict):
    honcho_usage = MagicMock()
    honcho_usage.cost_by_group.return_value = cost_by_group
    memory_groups = MagicMock()
    memory_groups.names_for_org.return_value = names
    return CostService(
        agent_repository=MagicMock(),
        agent_authorization=MagicMock(),
        permission_policy=MagicMock(),
        repository=MagicMock(),
        honcho_usage=honcho_usage,
        memory_groups=memory_groups,
    )


def test_scopes_to_the_orgs_groups_labels_them_and_ranks_by_cost() -> None:
    org, g1, g2, other = uuid7(), uuid7(), uuid7(), uuid7()
    # The apportionment returns every pool deployment-wide, including another org's.
    service = _service(
        {str(g1): 2.0, str(g2): 8.0, str(other): 99.0},
        {g1: "Research", g2: "Support"},
    )

    rows = service.memory_cost_by_group(_context(org), MagicMock())

    # Another org's group is excluded; ours are ranked by cost desc.
    assert_that([r.group_name for r in rows], contains_exactly("Support", "Research"))
    assert_that([r.memory_cost for r in rows], contains_exactly(8.0, 2.0))


def test_groups_with_no_memory_activity_show_zero() -> None:
    org, g1, idle = uuid7(), uuid7(), uuid7()
    service = _service({str(g1): 5.0}, {g1: "Research", idle: "Idle"})

    rows = service.memory_cost_by_group(_context(org), MagicMock())

    by_name = {r.group_name: r.memory_cost for r in rows}
    assert_that(by_name["Research"], equal_to(5.0))
    assert_that(by_name["Idle"], equal_to(0.0))


# --- memory spend per Organization, for budget enforcement (AF-338) ----------


def test_memory_spend_is_summed_per_organization_across_its_groups() -> None:
    org_a, org_b, a1, a2, b1 = uuid7(), uuid7(), uuid7(), uuid7(), uuid7()
    service = _service({str(a1): 2.0, str(a2): 3.0, str(b1): 7.0}, {})
    service.memory_groups.organization_by_group.return_value = {a1: org_a, a2: org_a, b1: org_b}

    by_org = service.memory_cost_by_organization(MagicMock(), MagicMock())

    assert_that(by_org, equal_to({org_a: 5.0, org_b: 7.0}))


def test_spend_on_a_pool_whose_group_is_gone_is_attributed_to_nobody() -> None:
    """A deleted group's pool can no longer be traced to an Organization. Its spend
    drops out rather than landing on the wrong one."""
    org, live, deleted = uuid7(), uuid7(), uuid7()
    service = _service({str(live): 1.0, str(deleted): 9.0}, {})
    service.memory_groups.organization_by_group.return_value = {live: org}

    assert_that(service.memory_cost_by_organization(MagicMock(), MagicMock()), equal_to({org: 1.0}))


def test_a_pool_workspace_that_is_not_a_group_id_is_skipped_not_fatal() -> None:
    """Workspace names come from Honcho telemetry. One malformed `af-pool-…` name
    must not stop every Organization's enforcement pass."""
    org, group = uuid7(), uuid7()
    service = _service({str(group): 2.0, "not-a-uuid": 5.0}, {})
    service.memory_groups.organization_by_group.return_value = {group: org}

    assert_that(service.memory_cost_by_organization(MagicMock(), MagicMock()), equal_to({org: 2.0}))
