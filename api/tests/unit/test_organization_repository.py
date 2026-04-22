from hamcrest import assert_that, equal_to, has_length, is_not, none

from api.domains.organizations.models import OrganizationFilter
from api.domains.organizations.repository import OrganizationRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization


def test_i_can_get_organization_read_with_owner_details():
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization(name="Owner Org"),
        ]
    ) as context:
        repository: OrganizationRepository = context.injector.get(
            OrganizationRepository
        )

        with when("I get organization read model"):
            org_read = repository.get_read(context.organization.id)

            with then("owner information should be present"):
                assert_that(org_read, is_not(none()))
                assert_that(org_read.name, equal_to("Owner Org"))
                assert_that(org_read.owner_email, is_not(none()))


def test_i_can_list_paginated_organizations():
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization(name="Org One"),
            there_is_an_organization(name="Org Two"),
        ]
    ) as context:
        repository: OrganizationRepository = context.injector.get(
            OrganizationRepository
        )

        with when("I list organizations"):
            result = repository.find_all_paginated_read(OrganizationFilter())

            with then("the organizations should be returned"):
                assert_that(result.items, has_length(2))
