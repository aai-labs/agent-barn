from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to

from api.core.config import Config
from api.domains.agents.repository import AgentRepository
from api.domains.organizations.llm import OrganizationLLMService
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule, there_is_an_agent
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


@pytest.mark.parametrize("platform", [False, True])
def test_both_creation_paths_provision_team(platform):
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="admin@example.com", organization_id=None, is_platform_admin=True),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        config = context.injector.get(Config)
        client = context.injector.get(LiteLLMClient)
        path = "/api/v1/platform/users" if platform else "/api/v1/organizations"
        body = (
            {"email": "new@example.com", "full_name": "New User", "organization_name": "New Org"}
            if platform
            else {"name": "New Org"}
        )
        with (
            patch.object(config, "litellm_base_url", "http://litellm"),
            patch.object(config, "litellm_secret_name", "litellm"),
        ):
            with when("an Organization is committed"):
                response = context.client.post(
                    path, json=body, headers={"Authorization": f"Bearer {context.access_token}"}
                )
        with then("its UUID identifies the LiteLLM team"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            org_id = response.json()["organization"]["id"] if platform else response.json()["id"]
            client.ensure_organization_team.assert_called_once_with(org_id)
            assert_that(context.injector.get(OrganizationRepository).get(UUID(org_id)) is not None, equal_to(True))


def test_system_inventory_scopes_keys_and_includes_deleted_agents():
    with given([*_GIVEN, there_is_an_organization(name="First")]) as context:
        first = context.organization.id
        there_is_an_agent(organization_id=first)(context)
        first_key = context.agent.litellm_key_encrypted
        there_is_an_agent(organization_id=first, deleted=True)(context)
        deleted_key = context.agent.litellm_key_encrypted
        there_is_an_organization(name="Second")(context)
        second = context.organization.id
        there_is_an_agent(organization_id=second)(context)
        with when("the system inventories one Organization's credentials"):
            result = context.injector.get(AgentRepository).list_llm_keys_for_reconciliation(first)
        with then("only that Organization's active and deleted keys are returned"):
            assert_that(result, contains_inanyorder(first_key, deleted_key))
            assert_that(
                context.injector.get(OrganizationRepository).list_ids_for_llm_reconciliation(),
                contains_inanyorder(first, second),
            )


def test_reconciliation_failure_is_visible_and_retryable():
    with given([*_GIVEN, there_is_an_organization()]) as context:
        config = context.injector.get(Config)
        client = context.injector.get(LiteLLMClient)
        service = context.injector.get(OrganizationLLMService)
        client.ensure_organization_team.side_effect = RuntimeError("unavailable")
        with (
            patch.object(config, "litellm_base_url", "http://litellm"),
            patch.object(config, "litellm_secret_name", "litellm"),
        ):
            with pytest.raises(RuntimeError):
                service.reconcile()
            client.ensure_organization_team.side_effect = None
            service.reconcile()
        assert_that(client.ensure_organization_team.call_count, equal_to(2))
