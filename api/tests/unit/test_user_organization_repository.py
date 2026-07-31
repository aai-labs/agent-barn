from hamcrest import assert_that, equal_to

from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user


def test_i_can_get_user_organization_by_user_and_org_id():
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization(),
            there_is_a_user(email="member@example.com", role=OrganizationRole.MEMBER),
        ]
    ) as context:
        repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)

        with when("I fetch organization membership"):
            user_id = context.user.id
            organization_id = context.organization.id
            result = repository.get_by_user_id_and_organization_id(user_id, organization_id)

            with then("membership should exist"):
                assert result is not None
                assert_that(result.role, equal_to(OrganizationRole.MEMBER))
