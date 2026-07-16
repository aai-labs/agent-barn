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
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

def test_catalog_access_by_non_admin_is_rejected():
    org_a = uuid7()
    member_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-catalog-owner@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_a,
                email="member-catalog@example.com",
                organization_id=org_a,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get(
            "/api/v1/agents/models?catalog=true",
            headers={
                "Authorization": f"Bearer {context.access_token}",
                "X-Organization-Id": str(org_a),
            },
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

def test_catalog_access_by_admin_is_allowed():
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-catalog@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get(
            "/api/v1/agents/models?catalog=true",
            headers={
                "Authorization": f"Bearer {context.access_token}",
                "X-Organization-Id": str(org_a),
            },
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
