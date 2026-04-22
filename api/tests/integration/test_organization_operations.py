from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, is_, is_not, none
from starlette.testclient import TestClient

from api.domains.organizations.models import OrganizationCreate
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def test_any_user_can_create_organization():
    super_user_id = uuid7()
    user_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_user_id, is_superuser=True, email="super@example.com"
            ),
            there_is_a_user(id=user_id, email="user@example.com"),
            there_is_an_access_token_for_user(user_id=user_id),
        ]
    ) as context:
        client: TestClient = context.client
        access_token = context.access_token
        organization_user_repository: OrganizationUserRepository = context.injector.get(
            OrganizationUserRepository
        )

        test_organization = OrganizationCreate(
            name="Test Organization",
            description="Test Organization Description",
        )

        with when("I create a new organization"):
            create_response = client.post(
                "/api/v1/organizations",
                json=test_organization.model_dump(),
                headers={"Authorization": f"Bearer {access_token}"},
            )

            with then("it should be created successfully"):
                assert_that(
                    create_response.status_code, equal_to(status.HTTP_201_CREATED)
                )
                payload = create_response.json()
                assert_that(payload["id"], is_not(none()))
                assert_that(payload["name"], equal_to(test_organization.name))
                assert_that(
                    payload["description"], equal_to(test_organization.description)
                )

            with then(
                "only the creating user should be added as an organization member"
            ):
                org_id = create_response.json()["id"]
                creator_org_user = (
                    organization_user_repository.get_by_user_id_and_organization_id(
                        user_id, org_id
                    )
                )
                super_admin_org_user = (
                    organization_user_repository.get_by_user_id_and_organization_id(
                        super_user_id, org_id
                    )
                )
                assert_that(creator_org_user, is_not(none()))
                assert_that(creator_org_user.role, equal_to(OrganizationRole.OWNER))
                assert_that(super_admin_org_user, is_(none()))
