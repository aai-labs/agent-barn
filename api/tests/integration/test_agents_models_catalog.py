from unittest.mock import patch
from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to
from sqlmodel import Session
from starlette.testclient import TestClient

from api.core.config import Config
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    OrganizationAccess,
)
from api.domains.organizations.models import Organization
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

LIST_MODELS = "api.infrastructure.openrouter.client.OpenRouterClient.list_models"
ALLOWED_MODEL = "openai/gpt-5-mini"
CATALOG = [{"id": ALLOWED_MODEL, "name": "GPT-5 mini"}, {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5"}]


def _setup(*steps):
    return [
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        *steps,
    ]


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
            f"/api/v1/organizations/{org_a}/agents/models?catalog=true",
            headers={"Authorization": f"Bearer {context.access_token}"},
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
        with patch(
            "api.infrastructure.openrouter.client.OpenRouterClient.list_models",
            return_value=[{"id": "openai/gpt-5-mini", "name": "GPT-5 mini"}],
        ):
            response = client.get(
                f"/api/v1/organizations/{org_a}/agents/models?catalog=true",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _owner_with_allowlist(context):
    there_is_a_user(email="owner-models@example.com", organization_id=uuid7(), role=OrganizationRole.OWNER)(context)
    there_is_an_access_token_for_user(user_id=context.user.id)(context)
    with Session(_engine(context)) as session:
        organization = session.get_one(Organization, context.organization.id)
        organization.allowed_models = [ALLOWED_MODEL]
        session.add(organization)
        session.commit()


def openrouter_access(access: OrganizationAccess, listed: str | None = None):
    def step(context):
        with Session(_engine(context)) as session:
            if listed == "other":
                other = Organization(name="Other Org")
                session.add(other)
                session.flush()
                listed_id = other.id
            else:
                listed_id = context.organization.id
            connection = session.get_one(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
            connection.organization_access = access
            session.add(connection)
            if listed is not None:
                session.add(LlmProviderConnectionOrganization(connection_id=connection.id, organization_id=listed_id))
            session.commit()

    return step


def _models(context, catalog: bool):
    with patch(LIST_MODELS, return_value=CATALOG) as listed:
        response = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/models",
            params={"catalog": "true"} if catalog else None,
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return response.json(), listed


@pytest.mark.parametrize("catalog", [False, True])
@pytest.mark.parametrize(
    ("access", "listed"),
    [(OrganizationAccess.NONE, None), (OrganizationAccess.ONLY, "other"), (OrganizationAccess.ALL_EXCEPT, "self")],
)
def test_an_organization_without_openrouter_access_is_offered_no_models(access, listed, catalog):
    with given(_setup(_owner_with_allowlist, openrouter_access(access, listed))) as context:
        models, catalogue = _models(context, catalog)

        assert_that(models, equal_to([]))
        catalogue.assert_not_called()


@pytest.mark.parametrize(
    ("access", "listed"),
    [(OrganizationAccess.ALL, None), (OrganizationAccess.ONLY, "self"), (OrganizationAccess.ALL_EXCEPT, "other")],
)
def test_an_organization_with_openrouter_access_is_offered_its_models_and_the_default(access, listed):
    with given(_setup(_owner_with_allowlist, openrouter_access(access, listed))) as context:
        default = context.injector.get(Config).agent_default_model

        models, _ = _models(context, catalog=False)
        catalogue, _ = _models(context, catalog=True)

        assert_that(
            [(model["value"], model["isDefault"]) for model in models],
            equal_to([(default, True), (f"litellm/openrouter/{ALLOWED_MODEL}", False)]),
        )
        assert_that(
            [model["value"] for model in catalogue],
            equal_to([default, *(f"litellm/openrouter/{model['id']}" for model in CATALOG)]),
        )
