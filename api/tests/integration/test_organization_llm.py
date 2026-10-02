from unittest.mock import patch

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_GIVEN = [
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]

BUDGET_PATH = "/api/v1/platform/organizations/{organization_id}/llm-budget"


def _platform_admin_context():
    # The user is created before the Organization: the user step joins whatever
    # Organization is already in context, which would collide with its owner.
    return [
        *_GIVEN,
        there_is_a_user(email="admin@example.com", is_platform_admin=True),
        there_is_an_access_token_for_user(),
        there_is_an_organization(),
    ]


def _litellm_configured(context):
    config = context.injector.get(Config)
    return (
        patch.object(config, "litellm_base_url", "http://litellm"),
        patch.object(config, "litellm_secret_name", "litellm"),
    )


def test_platform_admin_sets_a_budget_and_it_reaches_the_proxy():
    with given(_platform_admin_context()) as context:
        base_url, secret = _litellm_configured(context)
        organization_id = context.organization.id
        with base_url, secret:
            with when("a platform administrator sets the budget"):
                response = context.client.put(
                    BUDGET_PATH.format(organization_id=organization_id),
                    json={"budget_usd": 50, "budget_duration": "30d"},
                    headers={"Authorization": f"Bearer {context.access_token}"},
                )
        with then("it is stored on the Organization and mirrored onto its team"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["llm_budget_usd"], equal_to(50))
            stored = context.injector.get(OrganizationRepository).get(organization_id)
            assert_that(stored.llm_budget_usd, equal_to(50))
            context.injector.get(LiteLLMClient).apply_team_budget.assert_called_once_with(
                str(organization_id), 50, "30d"
            )


@pytest.mark.parametrize("payload", [{"budget_usd": -1}, {"budget_usd": 10, "budget_duration": "monthly"}])
def test_invalid_budgets_are_refused(payload):
    with given(_platform_admin_context()) as context:
        response = context.client.put(
            BUDGET_PATH.format(organization_id=context.organization.id),
            json=payload,
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(422))


def test_a_non_platform_admin_cannot_set_a_budget():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="member@example.com"),
            there_is_an_access_token_for_user(),
            there_is_an_organization(),
        ]
    ) as context:
        response = context.client.put(
            BUDGET_PATH.format(organization_id=context.organization.id),
            json={"budget_usd": 50},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


COVERAGE_PATH = "/api/v1/platform/organizations/{organization_id}/llm-budget/coverage"
ENROLL_PATH = "/api/v1/platform/organizations/{organization_id}/llm-budget/enroll"


def test_coverage_reports_agents_a_limit_would_not_bind():
    with given(_platform_admin_context()) as context:
        base_url, secret = _litellm_configured(context)
        client = context.injector.get(LiteLLMClient)
        client.get_key_team.return_value = None
        with base_url, secret:
            response = context.client.get(
                COVERAGE_PATH.format(organization_id=context.organization.id),
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
        with then("an Organization with no Agents is trivially covered"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total_agents"], equal_to(0))
            assert_that(response.json()["enrolled_agents"], equal_to(0))


@pytest.mark.parametrize("path", [COVERAGE_PATH, ENROLL_PATH])
def test_enrollment_surfaces_are_platform_only(path):
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="member@example.com"),
            there_is_an_access_token_for_user(),
            there_is_an_organization(),
        ]
    ) as context:
        url = path.format(organization_id=context.organization.id)
        headers = {"Authorization": f"Bearer {context.access_token}"}
        response = (
            context.client.get(url, headers=headers)
            if path is COVERAGE_PATH
            else context.client.post(url, headers=headers)
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


ORG_BUDGET_PATH = "/api/v1/organizations/{organization_id}/llm-budget"


def test_an_owner_sees_the_organizations_own_budget():
    with given(_platform_admin_context()) as context:
        response = context.client.get(
            ORG_BUDGET_PATH.format(organization_id=context.organization.id),
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        # Every Organization starts capped at the deployment default; spend has simply
        # not been observed yet, which is unknown rather than zero.
        assert_that(response.json()["state"], equal_to("unknown"))
        assert_that(response.json()["limit_usd"], equal_to(100.0))


def test_a_plain_member_cannot_see_the_organizations_budget():
    """Spend figures stay behind cost.read, which fixed roles grant to Owner/Admin."""
    with given(
        [
            *_GIVEN,
            # Organization first: the user step joins whatever Organization is in
            # context, which is how the member gets a MEMBER membership rather than
            # colliding with the owner.
            there_is_an_organization(),
            there_is_a_user(email="member@example.com", role=OrganizationRole.MEMBER),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        response = context.client.get(
            ORG_BUDGET_PATH.format(organization_id=context.organization.id),
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
