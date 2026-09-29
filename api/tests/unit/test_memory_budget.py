"""Memory spend against the Organization's LLM budget (AF-338).

Memory model calls run on Honcho's own LiteLLM key, which sits in no team, so the
team budget never sees them. Enforcement lowers the team's ceiling by the memory
spent this window instead, and suspends the Organization's memory once agents and
memory together reach the limit.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to

from api.domains.organizations.models import Organization, budget_window_start

RENEWS = datetime(2026, 10, 1, tzinfo=UTC)
IN_WINDOW = datetime(2026, 9, 20, tzinfo=UTC)
LAST_WINDOW = datetime(2026, 8, 20, tzinfo=UTC)


def organization(limit=100.0, own=None, memory=None, observed=IN_WINDOW, renews=RENEWS, window="30d"):
    return Organization(
        name="Acme",
        llm_budget_usd=limit,
        llm_own_budget_usd=own,
        llm_budget_duration=window,
        llm_budget_renews_at=renews,
        llm_memory_spend_usd=memory,
        llm_memory_spend_observed_at=observed if memory is not None else None,
    )


# --- where the window began -------------------------------------------------


@pytest.mark.parametrize(
    ("window", "renews", "expected"),
    [
        # LiteLLM snaps a 30d window to the 1st of the month, so it began on the
        # previous 1st — not 30 days back, which would miss or double-count a day.
        ("30d", datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)),
        ("30d", datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        ("30d", datetime(2026, 1, 1, tzinfo=UTC), datetime(2025, 12, 1, tzinfo=UTC)),
        ("7d", datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC)),
        ("1d", datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC)),
    ],
)
def test_a_window_began_one_period_before_it_renews(window, renews, expected):
    assert_that(budget_window_start(renews, window), equal_to(expected))


def test_a_30d_window_renewing_mid_month_began_the_same_day_a_month_earlier():
    """Teams created before LiteLLM snapped windows renew on whatever day they were set."""
    assert_that(
        budget_window_start(datetime(2026, 3, 31, tzinfo=UTC), "30d"),
        equal_to(datetime(2026, 2, 28, tzinfo=UTC)),
    )


# --- the ceiling pushed onto the team ---------------------------------------


def test_the_team_ceiling_is_the_limit_less_memory_spent_this_window():
    assert_that(organization(limit=100.0, memory=30.0).enforced_llm_budget_usd, equal_to(70.0))


def test_the_organizations_own_limit_is_what_memory_comes_off():
    assert_that(organization(limit=100.0, own=40.0, memory=10.0).enforced_llm_budget_usd, equal_to(30.0))


def test_unmeasured_memory_leaves_the_ceiling_at_the_limit():
    assert_that(organization(limit=100.0, memory=None).enforced_llm_budget_usd, equal_to(100.0))


def test_memory_measured_in_an_earlier_window_does_not_lower_this_one():
    """After a renewal the previous window's figure is stale until the next pass,
    and must not hold the fresh window down in the meantime."""
    assert_that(organization(limit=100.0, memory=30.0, observed=LAST_WINDOW).enforced_llm_budget_usd, equal_to(100.0))


def test_memory_with_no_known_window_does_not_lower_the_ceiling():
    assert_that(organization(limit=100.0, memory=30.0, renews=None).enforced_llm_budget_usd, equal_to(100.0))


def test_memory_alone_past_the_limit_takes_the_ceiling_to_zero_not_below():
    assert_that(organization(limit=100.0, memory=130.0).enforced_llm_budget_usd, equal_to(0.0))


def test_the_memory_spent_this_window_is_zero_when_it_is_stale():
    assert_that(organization(memory=30.0, observed=LAST_WINDOW).memory_spend_this_window_usd, equal_to(0.0))


# --- suspension holds for the window and limit it tripped under -------------


def test_an_organization_that_never_tripped_is_not_suspended():
    assert_that(organization().llm_memory_suspended, equal_to(False))


def test_a_trip_holds_while_the_window_and_limit_are_unchanged():
    org = organization(limit=100.0)
    org.llm_memory_suspended_key = org.llm_budget_window_key
    assert_that(org.llm_memory_suspended, equal_to(True))


def test_a_trip_lifts_when_the_window_renews():
    org = organization(limit=100.0)
    org.llm_memory_suspended_key = org.llm_budget_window_key
    org.llm_budget_renews_at = datetime(2026, 11, 1, tzinfo=UTC)
    assert_that(org.llm_memory_suspended, equal_to(False))


def test_a_trip_lifts_when_the_limit_changes():
    """Raising the limit mid-window is how an Organization buys its memory back."""
    org = organization(limit=100.0)
    org.llm_memory_suspended_key = org.llm_budget_window_key
    org.llm_own_budget_usd = 50.0
    assert_that(org.llm_memory_suspended, equal_to(False))


# --- every write of the team's limit pushes the lowered ceiling -------------


def test_a_new_team_is_provisioned_with_memory_already_off_its_ceiling():
    from api.tests.unit.test_organization_llm import configured, organization_service

    org = organization(limit=100.0, memory=30.0)
    service = organization_service()
    service.organization_repository.get.return_value = org
    with configured():
        service.provision_team(org.id)
    service.litellm.apply_team_budget.assert_called_once_with(str(org.id), 70.0, "30d")


def test_changing_the_limit_pushes_it_less_memory_but_holds_agents_to_the_real_limit():
    """Agent limits sit beneath the Organization's own figure, not the lowered one:
    the memory deduction is the team's alone, and an Agent's limit is its share of
    what the Organization chose to spend."""
    from api.tests.unit.test_organization_llm import acting, ceiling_service, configured

    org = organization(limit=100.0, memory=30.0)
    service = ceiling_service(org)
    with configured(), acting():
        service.set_llm_budget(org.id, 80.0, "30d", MagicMock())
    service.litellm.apply_team_budget.assert_called_once_with(str(org.id), 50.0, "30d")
    assert_that(service.agent_settings.lower_default_agent_llm_budget.call_args.args[1], equal_to(80.0))


# --- the enforcement pass ----------------------------------------------------

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
TEAM_RENEWS = "2026-10-01T00:00:00+00:00"


def enforcement(orgs, agent_spend, memory_by_org, *, percent=100, renews=TEAM_RENEWS):
    from api.domains.organizations.memory_budget import OrganizationMemoryBudgetService
    from api.tests.unit.test_organization_llm import config

    repo = MagicMock()
    repo.list_capped_organizations.return_value = orgs
    by_id = {org.id: org for org in orgs}

    def record(organization_id, *, memory_spend_usd, observed_at, renews_at, suspended_key):
        org = by_id[organization_id]
        org.llm_memory_spend_usd = memory_spend_usd
        org.llm_memory_spend_observed_at = observed_at
        org.llm_budget_renews_at = renews_at
        org.llm_memory_suspended_key = suspended_key
        return org

    repo.record_memory_budget.side_effect = record
    litellm = MagicMock()
    litellm.get_team_budget_status.side_effect = lambda team_id: (
        {"spend": agent_spend[team_id], "renews_at": renews} if team_id in agent_spend else None
    )
    memory_costs = MagicMock()
    memory_costs.memory_cost_by_organization.return_value = memory_by_org
    service = OrganizationMemoryBudgetService(organization_repository=repo, litellm=litellm, memory_costs=memory_costs)
    settings = config(llm_memory_suspend_percent=percent)
    return service, patch("api.domains.organizations.memory_budget.get_config", return_value=settings)


def enforced(service):
    """The per-Organization write the pass made, keyed by Organization."""
    return {c.args[0]: c.kwargs for c in service.organization_repository.record_memory_budget.call_args_list}


def run_pass(service, settings):
    with settings, patch("api.domains.organizations.memory_budget._now", return_value=NOW):
        service.enforce_memory_budgets()


def test_memory_spend_is_measured_over_the_window_and_comes_off_the_ceiling():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 20.0}, {org.id: 30.0})
    run_pass(service, settings)

    start, end = service.memory_costs.memory_cost_by_organization.call_args.args
    assert_that((start, end), equal_to((datetime(2026, 9, 1, tzinfo=UTC), NOW)))
    written = enforced(service)[org.id]
    assert_that(written["memory_spend_usd"], equal_to(30.0))
    assert_that(written["suspended_key"], equal_to(None))
    service.litellm.apply_team_budget.assert_called_once_with(str(org.id), 70.0, "30d")


def test_an_organization_with_no_memory_is_measured_at_zero():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 20.0}, {})
    run_pass(service, settings)
    assert_that(enforced(service)[org.id]["memory_spend_usd"], equal_to(0.0))
    service.litellm.apply_team_budget.assert_called_once_with(str(org.id), 100.0, "30d")


def test_agents_and_memory_together_reaching_the_limit_suspend_memory():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 60.0}, {org.id: 40.0})
    run_pass(service, settings)
    assert_that(enforced(service)[org.id]["suspended_key"], equal_to(f"{TEAM_RENEWS}|100.0"))


def test_combined_spend_below_the_limit_leaves_memory_on():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 60.0}, {org.id: 39.0})
    run_pass(service, settings)
    assert_that(enforced(service)[org.id]["suspended_key"], equal_to(None))


def test_a_deployment_can_trip_early_to_absorb_the_overshoot_between_passes():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 60.0}, {org.id: 35.0}, percent=95)
    run_pass(service, settings)
    assert_that(enforced(service)[org.id]["suspended_key"], equal_to(f"{TEAM_RENEWS}|100.0"))


def test_memory_alone_past_the_limit_blocks_agents_and_suspends_memory():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 0.0}, {org.id: 130.0})
    run_pass(service, settings)
    service.litellm.apply_team_budget.assert_called_once_with(str(org.id), 0.0, "30d")
    assert_that(enforced(service)[org.id]["suspended_key"], equal_to(f"{TEAM_RENEWS}|100.0"))


def test_a_trip_holds_even_when_the_memory_figure_later_dips():
    """Apportionment shifts as other pools grow, so the figure can fall. The trip
    holds until the window renews or the limit changes, rather than flapping."""
    org = organization(limit=100.0, renews=datetime(2026, 10, 1, tzinfo=UTC))
    org.llm_memory_suspended_key = org.llm_budget_window_key
    service, settings = enforcement([org], {str(org.id): 10.0}, {org.id: 5.0})
    run_pass(service, settings)
    assert_that(enforced(service)[org.id]["suspended_key"], equal_to(org.llm_budget_window_key))


def test_an_unreadable_team_writes_nothing_for_that_organization():
    """An unreadable team is not a team that spent nothing: no snapshot, no push."""
    org = organization(limit=100.0)
    service, settings = enforcement([org], {}, {org.id: 30.0})
    run_pass(service, settings)
    assert_that(enforced(service), equal_to({}))
    service.litellm.apply_team_budget.assert_not_called()


def test_a_team_with_no_renewal_date_is_skipped():
    org = organization(limit=100.0, renews=None)
    service, settings = enforcement([org], {str(org.id): 1.0}, {}, renews=None)
    run_pass(service, settings)
    assert_that(enforced(service), equal_to({}))


def test_one_failing_organization_does_not_stop_the_pass():
    from api.infrastructure.litellm.client import LiteLLMError

    first, second = organization(limit=100.0, renews=None), organization(limit=50.0, renews=None)
    service, settings = enforcement([first, second], {str(first.id): 1.0, str(second.id): 1.0}, {})
    service.litellm.apply_team_budget.side_effect = [LiteLLMError("down"), None]
    run_pass(service, settings)
    assert_that(service.litellm.apply_team_budget.call_count, equal_to(2))


def test_the_pass_is_skipped_when_litellm_is_not_configured():
    from api.domains.organizations.memory_budget import OrganizationMemoryBudgetService
    from api.tests.unit.test_organization_llm import config

    repository = MagicMock()
    service = OrganizationMemoryBudgetService(
        organization_repository=repository, litellm=MagicMock(), memory_costs=MagicMock()
    )
    with patch(
        "api.domains.organizations.memory_budget.get_config",
        return_value=config(litellm_base_url="", litellm_secret_name=""),
    ):
        service.enforce_memory_budgets()
    repository.list_capped_organizations.assert_not_called()


@pytest.mark.parametrize("percent", [0, 101])
def test_a_suspend_percent_outside_1_to_100_is_refused(percent):
    from pydantic import ValidationError

    from api.tests.unit.test_organization_llm import config

    with pytest.raises(ValidationError):
        config(llm_memory_suspend_percent=percent)


def test_the_enforcement_cronjob_runs_one_pass():
    from api.domains.organizations import llm_budget_cron, llm_budget_enforcement

    service = MagicMock()
    with (
        patch.object(llm_budget_cron, "build_service", return_value=service) as build,
        patch("sys.argv", ["llm-budget-enforcement"]),
    ):
        llm_budget_enforcement.main()
    service.enforce_memory_budgets.assert_called_once_with()
    from api.domains.organizations.memory_budget import OrganizationMemoryBudgetService

    assert_that(build.call_args.args, equal_to((OrganizationMemoryBudgetService,)))


# --- the budget surfaces show agents + memory against the real limit ---------


def viewed_with_memory(memory, observed=None, spend=40.0, limit=100.0):
    from api.tests.unit.test_organization_llm import viewed

    org = viewed(limit=limit, spend=spend)
    org.llm_memory_spend_usd = memory
    org.llm_memory_spend_observed_at = observed or datetime.now(UTC)
    return org


def test_an_organization_sees_agents_and_memory_against_its_real_limit():
    from api.tests.unit.test_organization_llm import org_budget_service

    service = org_budget_service(viewed_with_memory(35.0))
    read = service.get_organization_llm_budget(MagicMock(), MagicMock())
    assert_that((read.limit_usd, read.spend_usd, read.memory_spend_usd), equal_to((100.0, 75.0, 35.0)))


def test_memory_that_takes_the_total_to_the_limit_shows_it_exhausted():
    from api.tests.unit.test_organization_llm import org_budget_service

    service = org_budget_service(viewed_with_memory(60.0))
    assert_that(service.get_organization_llm_budget(MagicMock(), MagicMock()).state, equal_to("exhausted"))


def test_last_windows_memory_is_not_shown_as_this_windows():
    from api.tests.unit.test_organization_llm import org_budget_service

    service = org_budget_service(viewed_with_memory(35.0, observed=datetime(2026, 8, 20, tzinfo=UTC)))
    read = service.get_organization_llm_budget(MagicMock(), MagicMock())
    assert_that((read.spend_usd, read.memory_spend_usd), equal_to((40.0, 0.0)))


def test_alerts_fire_on_agents_and_memory_together_but_the_snapshot_stays_agents_only():
    """The snapshot is the proxy's figure for the team; memory has its own column.
    Each writer owns one number and the surfaces add them."""
    from api.tests.unit.test_organization_llm import budget_service, configured

    org = viewed_with_memory(30.0, spend=None)
    org.llm_budget_renews_at = None
    service = budget_service([org], {str(org.id): {"spend": 60.0, "renews_at": "2026-10-01T00:00:00+00:00"}})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([(c.threshold_percent, c.spend_usd) for c in fired], equal_to([(80, 90.0)]))
    assert_that(org.llm_spend_usd, equal_to(60.0))


def test_the_platform_coverage_view_counts_memory_in_the_teams_spend():
    from api.tests.unit.test_organization_llm import configured, organization_service

    org = viewed_with_memory(25.0)
    service = organization_service()
    service.organization_repository.get.return_value = org
    service.agent_budgets.llm_credentials.return_value = []
    service.litellm.get_team_budget_status.return_value = {"spend": 10.0, "renews_at": None}
    with configured():
        coverage = service.get_llm_coverage(org.id)
    assert_that(coverage.spend_usd, equal_to(35.0))


# --- other domains ask whether an Organization's memory is suspended ---------


@pytest.mark.parametrize(("tripped", "expected"), [(True, True), (False, False)])
def test_the_lookup_reports_whether_memory_is_suspended(tripped, expected):
    from api.domains.organizations.lookup import OrganizationLookupService

    org = organization()
    if tripped:
        org.llm_memory_suspended_key = org.llm_budget_window_key
    repository = MagicMock()
    repository.get.return_value = org
    assert_that(OrganizationLookupService(repository=repository).memory_suspended(org.id), equal_to(expected))


def test_a_missing_organization_is_not_suspended():
    from api.domains.organizations.lookup import OrganizationLookupService

    repository = MagicMock()
    repository.get.return_value = None
    assert_that(OrganizationLookupService(repository=repository).memory_suspended(MagicMock()), equal_to(False))
