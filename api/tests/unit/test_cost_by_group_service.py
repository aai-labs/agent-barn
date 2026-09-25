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
