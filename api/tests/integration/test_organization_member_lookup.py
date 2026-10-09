from uuid import uuid7

from hamcrest import assert_that, equal_to, none

from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token

_GIVEN = [
    prepare_injector(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def test_finds_the_member_and_user_by_membership_id_within_its_organization():
    with given(_GIVEN) as context:
        repository = context.injector.get(OrganizationUserRepository)

        found = repository.get_member_with_user_by_membership_id(context.organization_user.id, context.organization.id)

        assert found is not None
        membership, user = found
        assert_that((membership.id, user.id), equal_to((context.organization_user.id, context.user.id)))


def test_does_not_find_a_membership_of_another_organization():
    with given(_GIVEN) as context:
        membership_id = context.organization_user.id
        there_is_an_organization(name="Other Organization")(context)
        repository = context.injector.get(OrganizationUserRepository)

        found = repository.get_member_with_user_by_membership_id(membership_id, context.organization.id)

        assert_that(found, none())


def test_does_not_find_a_missing_membership():
    with given(_GIVEN) as context:
        repository = context.injector.get(OrganizationUserRepository)

        found = repository.get_member_with_user_by_membership_id(uuid7(), context.organization.id)

        assert_that(found, none())
