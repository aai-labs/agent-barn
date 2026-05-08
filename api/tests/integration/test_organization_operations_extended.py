from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to
from starlette.testclient import TestClient

from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def test_regular_user_lists_only_their_organizations():
    org_a = uuid7()
    org_b = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-list-a@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-list-b@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get(
            "/api/v1/organizations",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(len(response.json()["items"]), equal_to(1))
        assert_that(response.json()["items"][0]["id"], equal_to(str(org_a)))


def test_superuser_can_update_any_organization():
    org_id = uuid7()
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-super-update@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=super_id,
                email="super-update@example.com",
                is_superuser=True,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Updated By Super Admin"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["name"], equal_to("Updated By Super Admin"))


def test_member_cannot_update_organization():
    org_id = uuid7()
    owner_id = uuid7()
    member_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_id,
                email="owner@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Should Not Work"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_superuser_gets_404_for_missing_organization():
    super_id = uuid7()
    missing_org = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super@example.com", is_superuser=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            f"/api/v1/organizations/{missing_org}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_member_cannot_delete_organization():
    org_id = uuid7()
    owner_id = uuid7()
    member_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_id,
                email="owner-delete2@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_id,
                email="member-delete2@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_superuser_can_delete_any_organization():
    super_id = uuid7()
    org_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id, email="super-admin@example.com", is_superuser=True
            ),
            there_is_a_user(
                email="owner-admin-delete@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
