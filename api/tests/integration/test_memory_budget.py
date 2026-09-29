"""The reconciler's inventory of team limits, read from real Organization rows (AF-338)."""

from datetime import UTC, datetime

from hamcrest import assert_that, equal_to

from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready


def test_the_reconciler_pushes_each_limit_less_the_memory_spent_this_window():
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        repository = context.injector.get(OrganizationRepository)
        with_memory = repository.save(
            Organization(
                name="With memory",
                llm_budget_usd=100.0,
                llm_own_budget_usd=60.0,
                llm_budget_renews_at=datetime(2099, 1, 1, tzinfo=UTC),
                llm_memory_spend_usd=15.0,
                llm_memory_spend_observed_at=datetime(2098, 12, 20, tzinfo=UTC),
            )
        )
        without = repository.save(Organization(name="No memory", llm_budget_usd=40.0))

        policies = {org_id: (budget, window) for org_id, budget, window in repository.list_budget_policies()}

        assert_that(policies[with_memory.id], equal_to((45.0, "30d")))
        assert_that(policies[without.id], equal_to((40.0, "30d")))
