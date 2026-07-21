import hashlib
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.domains.rbac.catalog import PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/costs"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
    there_is_an_agent(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _there_is_a_member_actor(member_id):
    """Attach a plain MEMBER to the org set up in _GIVEN and switch the token to them."""

    def step(context):
        there_is_a_user(
            id=member_id,
            email="member-costs@example.com",
            role=OrganizationRole.MEMBER,
        )(context)
        there_is_an_access_token_for_user(user_id=member_id)(context)

    return step


def test_admin_with_assigned_cost_scope_cannot_view_organization_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-assigned-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
            role_lacks_permission(
                OrganizationRole.ADMIN,
                PermissionKey.COST_READ,
            ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_cost_read_cannot_view_organization_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-no-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.COST_READ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_with_organization_cost_scope_can_view_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
        ]
    ) as context:
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        litellm.get_global_spend_report.return_value = {}

        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_member_cannot_view_costs_summary():
    """Org spend is sensitive: only owners/admins (and superusers) may view it."""
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_view_agent_cost():
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        agent_id = str(context.agent.id)
        response = context.client.get(
            f"{_BASE}/agents/{agent_id}", headers=_auth(context)
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_superuser_can_view_costs_summary():
    """Superusers transcend org roles: the owner/admin gate must not block them, even
    though a superuser isn't a member of the org they're viewing (membership is
    synthesized from the active-org header)."""
    super_id = uuid7()
    org_id = uuid7()
    with given(
        [
            set_env_variable(
                {
                    "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                    "LITELLM_BASE_URL": "http://litellm:4000",
                    "LITELLM_SECRET_NAME": "litellm",
                    "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                    "SKIP_SLACK_TOKEN_VALIDATION": "true",
                }
            ),
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            # Created before the org exists in context, so the superuser stays a non-member.
            there_is_a_user(
                id=super_id, email="super-costs@example.com", is_superuser=True
            ),
            there_is_an_organization_with_user_and_access_token(
                id=org_id, email="owner-super-costs@example.com"
            ),
            use_org_for_auth(),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        litellm.get_global_spend_report.return_value = {}
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_get_costs_summary_returns_200_and_data():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)

        key_hash = hashlib.sha256(FAKE_LITELLM_KEY.encode()).hexdigest()

        litellm.get_global_spend_report.return_value = {
            key_hash: {
                "spend": 10.5,
                "total_input_tokens": 100,
                "total_output_tokens": 50,
                "models": {
                    "gpt-4": {
                        "spend": 10.5,
                        "total_input_tokens": 100,
                        "total_output_tokens": 50,
                    }
                },
            }
        }

        with when("I request the costs summary"):
            response = client.get(f"{_BASE}/summary", headers=_auth(context))

        with then("it returns 200 with the correct aggregation"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["totalCost"], equal_to(10.5))
            assert_that(data["agents"], has_length(1))
            assert_that(data["agents"][0]["total_cost"], equal_to(10.5))
            assert_that(data["agents"][0]["prompt_tokens"], equal_to(100))
            assert_that(data["byModel"], has_length(1))


def test_get_agent_cost_returns_200_and_data():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        agent_id = str(context.agent.id)

        litellm.get_key_info.return_value = {
            "spend": 5.0,
        }

        with when("I request the individual agent cost"):
            response = client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("it returns 200 with the agent's cost"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["total_cost"], equal_to(5.0))
            assert_that(data["agent_id"], equal_to(agent_id))


def test_get_costs_summary_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I request costs summary without auth"):
            response = client.get(f"{_BASE}/summary")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I request agent cost without auth"):
            response = client.get(f"{_BASE}/agents/{agent_id}")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "11111111-1111-1111-1111-111111111111"

        with when("I request an agent that does not exist"):
            response = client.get(f"{_BASE}/agents/{fake_id}", headers=_auth(context))

        with then("it returns 404 Not Found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
