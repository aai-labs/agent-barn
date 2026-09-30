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


def test_a_suspension_still_matches_after_the_row_is_saved_and_read_back():
    """The key embeds the renewal timestamp; it must render the same from a freshly
    parsed LiteLLM value and from the database."""
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        repository = context.injector.get(OrganizationRepository)
        organization = Organization(
            name="Suspended",
            llm_budget_usd=100.0,
            llm_budget_renews_at=datetime.fromisoformat("2099-01-01T00:00:00Z"),
        )
        organization.llm_memory_suspended_key = organization.llm_budget_window_key
        saved = repository.save(organization)

        assert_that(repository.get(saved.id).llm_memory_suspended, equal_to(True))
