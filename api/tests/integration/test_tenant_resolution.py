"""URL-scoped tenant resolution for organization routes.

The active organization is resolved from the organization_id path parameter,
validated against membership in get_current_user, and drives org-scoped resource
queries. Platform Administrators may target any org through an explicit org URL.
"""

from uuid import UUID

from fastapi import status
from hamcrest import assert_that, equal_to, has_item, not_

from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    MockK8sModule,
    MockLiteLLMModule,
    TEST_ENCRYPTION_KEY,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.user import (
    there_is_a_user,
    there_is_an_access_token_for_user,
)


def _agents(org_id: UUID | str) -> str:
    return f"/api/v1/organizations/{org_id}/agents"


ORG_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MEMBER_A = UUID("11111111-1111-1111-1111-111111111111")
SUPERUSER = UUID("22222222-2222-2222-2222-222222222222")

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _there_is_a_bare_org(org_id: UUID, name: str):
    """Insert a plain Organization row without coupling an owner user to it."""

    def step(context):
        repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        repo.save(Organization(id=org_id, name=name))

    return step


def _agent_names(response) -> list[str]:
    return [item["name"] for item in response.json()["items"]]


def _there_is_an_assigned_agent(org_id: UUID, name: str):
    def step(context):
        there_is_an_agent(
            organization_id=org_id,
            name=name,
            created_by_user_id=context.user.id,
            creator_membership_id=context.organization_user.id,
        )(context)

    return step


def test_member_lists_agents_scoped_to_url_org():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=MEMBER_A,
                email="member-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(),
            _there_is_a_bare_org(ORG_B, "Org B"),
            _there_is_an_assigned_agent(ORG_A, "Agent A"),
            there_is_an_agent(organization_id=ORG_B, name="Agent B"),
        ]
    ) as context:
        with when("member lists agents under org A URL"):
            response = context.client.get(
                _agents(ORG_A),
                headers=_auth(context),
            )

            with then("only org A agents are returned"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(_agent_names(response), has_item("Agent A"))
                assert_that(_agent_names(response), not_(has_item("Agent B")))


def test_member_targeting_foreign_org_is_forbidden():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=MEMBER_A,
                email="member-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(),
            _there_is_a_bare_org(ORG_B, "Org B"),
        ]
    ) as context:
        with when("member requests an org URL they do not belong to"):
            response = context.client.get(
                _agents(ORG_B),
                headers=_auth(context),
            )

            with then("request is forbidden"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_can_target_any_org_and_is_isolated_per_url():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=SUPERUSER,
                email="root@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_an_access_token_for_user(),
            _there_is_a_bare_org(ORG_A, "Org A"),
            _there_is_a_bare_org(ORG_B, "Org B"),
            there_is_an_agent(organization_id=ORG_A, name="Agent A"),
            there_is_an_agent(organization_id=ORG_B, name="Agent B"),
        ]
    ) as context:
        with when("platform_admin targets org A"):
            response_a = context.client.get(
                _agents(ORG_A),
                headers=_auth(context),
            )
        with when("platform_admin targets org B"):
            response_b = context.client.get(
                _agents(ORG_B),
                headers=_auth(context),
            )

            with then("each request sees only its targeted org's agents"):
                assert_that(response_a.status_code, equal_to(status.HTTP_200_OK))
                assert_that(_agent_names(response_a), has_item("Agent A"))
                assert_that(_agent_names(response_a), not_(has_item("Agent B")))

                assert_that(response_b.status_code, equal_to(status.HTTP_200_OK))
                assert_that(_agent_names(response_b), has_item("Agent B"))
                assert_that(_agent_names(response_b), not_(has_item("Agent A")))


def test_malformed_url_org_id_is_rejected():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=MEMBER_A,
                email="member-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        with when("the organization_id path parameter is not a valid UUID"):
            response = context.client.get(
                _agents("not-a-uuid"),
                headers=_auth(context),
            )

            with then("request is rejected as bad request"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_old_unscoped_agent_route_is_not_available():
    with given(
        [
            *_GIVEN,
            there_is_an_organization_with_user_and_access_token(id=ORG_A, name="Org A", email="owner@example.com"),
            there_is_an_agent(organization_id=ORG_A, name="Agent A"),
        ]
    ) as context:
        with when("the old unscoped agent route is called"):
            response = context.client.get("/api/v1/agents", headers=_auth(context))

            with then("the route is not available"):
                assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
