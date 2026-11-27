from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to
from sqlalchemy import delete
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    LlmProviderModel,
    OrganizationAccess,
    PriceSource,
    ProviderType,
)
from api.domains.organizations.models import Organization
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

BASE = "/api/v1/organizations/{organization_id}/agents"
CREATE = {"name": "Sales", "template_key": "test-template"}
NO_PROVIDER = "This organization has no LLM provider. Ask a Platform Administrator."
NO_OPENROUTER = "This organization can't use OpenRouter. Ask a Platform Administrator."
ANTHROPIC_MODEL = "claude-sonnet-4-5"
ANTHROPIC_ENTRY = f"anthropic/{ANTHROPIC_MODEL}"
ANTHROPIC_DEFAULT = f"litellm/{ANTHROPIC_ENTRY}"
NO_ACCESS = [
    (OrganizationAccess.NONE, None),
    (OrganizationAccess.ONLY, "other"),
    (OrganizationAccess.ALL_EXCEPT, "self"),
]
WITH_ACCESS = [
    (OrganizationAccess.ALL, None),
    (OrganizationAccess.ONLY, "self"),
    (OrganizationAccess.ALL_EXCEPT, "other"),
]


def _setup(*steps):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/openrouter/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "API_EXTERNAL_URL": "https://api.test.com",
                "SKIP_SLACK_TOKEN_VALIDATION": "true",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(allowed_models=["*"]),
        use_org_for_auth(),
        there_is_a_template(),
        *steps,
    ]


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _set_openrouter_access(context, access: OrganizationAccess, listed: str | None = None) -> None:
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


def openrouter_access(access: OrganizationAccess, listed: str | None = None):
    def step(context):
        _set_openrouter_access(context, access, listed)

    return step


def parent_agent(context):
    there_is_an_agent(name="Parent", agent_type=AgentType.HERMES, status=AgentStatus.STOPPED)(context)
    context.parent = context.agent


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _hire(context, **fields):
    return context.client.post(BASE, json={**CREATE, **fields}, headers=_auth(context))


def _add_bot(context, **fields):
    return context.client.post(f"{BASE}/{context.parent.id}/bots", json={**CREATE, **fields}, headers=_auth(context))


def _hired(context) -> list[str]:
    with Session(_engine(context)) as session:
        return list(
            session.exec(
                select(Agent.name).where(Agent.organization_id == context.organization.id, col(Agent.name) == "Sales")
            ).all()
        )


def _litellm(context) -> MagicMock:
    return context.injector.get(LiteLLMClient)


@pytest.mark.parametrize("model", [None, "litellm/openrouter/openai/gpt-4o"])
@pytest.mark.parametrize(("access", "listed"), NO_ACCESS)
def test_an_organization_without_openrouter_access_cannot_hire(access, listed, model):
    with given(_setup(openrouter_access(access, listed))) as context:
        response = _hire(context, **({"model": model} if model else {}))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(NO_PROVIDER))
        _litellm(context).generate_key.assert_not_called()
        assert_that(_hired(context), equal_to([]))


def test_an_organization_without_openrouter_access_cannot_add_a_bot():
    with given(_setup(parent_agent, openrouter_access(OrganizationAccess.NONE))) as context:
        response = _add_bot(context)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(NO_PROVIDER))
        _litellm(context).generate_key.assert_not_called()
        assert_that(_hired(context), equal_to([]))


def test_access_withdrawn_after_the_first_check_refuses_the_hire_and_releases_the_key():
    with given(_setup()) as context:
        litellm = _litellm(context)

        def withdraw_while_the_key_is_made(*args, **kwargs):
            _set_openrouter_access(context, OrganizationAccess.NONE)
            return FAKE_LITELLM_KEY

        litellm.generate_key.side_effect = withdraw_while_the_key_is_made

        response = _hire(context)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(NO_PROVIDER))
        litellm.generate_key.assert_called_once()
        litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
        assert_that(_hired(context), equal_to([]))


@pytest.mark.parametrize(("access", "listed"), WITH_ACCESS)
def test_an_organization_with_openrouter_access_hires_and_adds_bots(access, listed):
    with given(_setup(parent_agent, openrouter_access(access, listed))) as context:
        hired = _hire(context)
        bot = _add_bot(context)

        assert_that((hired.status_code, bot.status_code), equal_to((201, 201)), f"{hired.text} {bot.text}")
        assert_that(_hired(context), equal_to(["Sales", "Sales"]))


def an_anthropic_connection(access: OrganizationAccess = OrganizationAccess.ALL):
    def step(context):
        with Session(_engine(context)) as session:
            connection = LlmProviderConnection(
                slug="anthropic", name="Anthropic", provider_type=ProviderType.ANTHROPIC, organization_access=access
            )
            session.add(connection)
            session.flush()
            session.add(
                LlmProviderModel(
                    connection_id=connection.id,
                    model_id=ANTHROPIC_MODEL,
                    input_cost_per_token=Decimal("0.000003"),
                    output_cost_per_token=Decimal("0.000015"),
                    cache_read_input_token_cost=Decimal(0),
                    cache_creation_input_token_cost=Decimal(0),
                    price_source=PriceSource.MANUAL,
                )
            )
            session.commit()

    return step


def _remove_the_anthropic_model(context) -> None:
    with Session(_engine(context)) as session:
        session.exec(delete(LlmProviderModel).where(col(LlmProviderModel.model_id) == ANTHROPIC_MODEL))
        session.commit()


def test_a_hire_and_a_bot_on_another_open_connection_succeed_without_openrouter():
    with given(_setup(parent_agent, openrouter_access(OrganizationAccess.NONE), an_anthropic_connection())) as context:
        hired = _hire(context, model=ANTHROPIC_DEFAULT)
        bot = _add_bot(context, model=ANTHROPIC_DEFAULT)

        assert_that((hired.status_code, bot.status_code), equal_to((201, 201)), f"{hired.text} {bot.text}")
        assert_that(_hired(context), equal_to(["Sales", "Sales"]))


def test_a_hire_or_a_bot_inheriting_the_openrouter_platform_default_is_refused_without_openrouter():
    with given(_setup(parent_agent, openrouter_access(OrganizationAccess.NONE), an_anthropic_connection())) as context:
        hired = _hire(context)
        bot = _add_bot(context)

        assert_that((hired.status_code, bot.status_code), equal_to((400, 400)))
        assert_that((hired.json()["detail"], bot.json()["detail"]), equal_to((NO_OPENROUTER, NO_OPENROUTER)))
        _litellm(context).generate_key.assert_not_called()
        assert_that(_hired(context), equal_to([]))


def test_a_model_removed_after_the_first_check_refuses_the_hire_and_releases_the_key():
    with given(_setup(an_anthropic_connection())) as context:
        litellm = _litellm(context)

        def remove_while_the_key_is_made(*args, **kwargs):
            _remove_the_anthropic_model(context)
            return FAKE_LITELLM_KEY

        litellm.generate_key.side_effect = remove_while_the_key_is_made

        response = _hire(context, model=ANTHROPIC_DEFAULT)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(f"Model '{ANTHROPIC_ENTRY}' is not one of Anthropic's models."))
        litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
        assert_that(_hired(context), equal_to([]))
