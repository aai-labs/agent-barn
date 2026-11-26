import json
from uuid import UUID

import pytest
from hamcrest import assert_that, equal_to
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from api.core.config import Config
from api.domains.agent_settings.models import OrganizationAgentSettings
from api.domains.agents.key_models import AgentKeyModelService
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockLiteLLMModule,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

PLATFORM_DEFAULT = "litellm/openrouter/z-ai/glm-5.2"
DECISION_MODELS = {"jev": "openrouter/typesafe/jev-1.14", "openai": "openrouter/openai/gpt-6-luna-decisions"}
PLAYBOOK_MODEL = "openrouter/openai/gpt-4.1-mini"
PLATFORM_MODELS = [PLAYBOOK_MODEL, *DECISION_MODELS.values()]
EXPLICIT_MODEL = "litellm/openrouter/openai/gpt-5-nano"
ORGANIZATION_DEFAULT = "litellm/openrouter/qwen/qwen3.6-plus"
RUNNING_MODEL = "litellm/openrouter/openrouter/free"
STARTING_MODEL = "litellm/openrouter/anthropic/claude-sonnet-4.5"
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '200ms'"
DELETED_MODEL = "litellm/openrouter/deleted/model"
KEYLESS_MODEL = "litellm/openrouter/keyless/model"
FAILING_MODEL = "litellm/openrouter/failing/model"


def _setup(model: str = "", *steps):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": PLATFORM_DEFAULT,
                "DECISION_MODELS": json.dumps(DECISION_MODELS),
                "PLAYBOOK_DEFAULT_MODEL": PLAYBOOK_MODEL,
            }
        ),
        prepare_injector(modules=[MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(),
        there_is_an_agent(model=model),
        *steps,
    ]


def _organization_default_is(model: str):
    def step(context):
        with Session(context.postgres_delegate.engine) as session:
            session.add(OrganizationAgentSettings(organization_id=context.organization.id, default_model=model))
            session.commit()

    return step


def _stored(context, **fields) -> Agent:
    repository = context.injector.get(AgentRepository)
    agent = repository.get_by_id(context.agent.id)
    for name, value in fields.items():
        setattr(agent, name, value)
    return repository.save(agent)


def _models_for(context, starting_model: str | None = None) -> list[str]:
    agent = context.injector.get(AgentRepository).get_by_id(context.agent.id)
    return context.injector.get(AgentKeyModelService).models_for(agent, starting_model)


def _with(*models: str) -> list[str]:
    return sorted({*models, *PLATFORM_MODELS})


def _own_models_synced(context) -> list[list[str]]:
    calls = context.injector.get(LiteLLMClient).set_key_models.call_args_list
    return [[model for model in call.args[1] if model not in PLATFORM_MODELS] for call in calls]


def _refuse_failing_model(_key: str, models: list[str]) -> bool:
    if "openrouter/failing/model" in models:
        raise LiteLLMError("Failed to set the Agent key's models")
    return True


def _try_lock(context, agent_id: UUID) -> None:
    with Session(context.postgres_delegate.engine) as other:
        other.connection().execute(text(LOCK_TIMEOUT))
        AgentRepository.lock_key_models(other, agent_id)


def test_an_agents_explicit_model_is_listed_with_the_platform_models():
    with given(_setup(EXPLICIT_MODEL)) as context:
        assert_that(_models_for(context), equal_to(_with("openrouter/openai/gpt-5-nano")))


def test_an_inheriting_agent_lists_its_organizations_default():
    with given(_setup("", _organization_default_is(ORGANIZATION_DEFAULT))) as context:
        assert_that(_models_for(context), equal_to(_with("openrouter/qwen/qwen3.6-plus")))


def test_an_inheriting_agent_without_an_organization_default_lists_the_platform_default():
    with given(_setup()) as context:
        assert_that(_models_for(context), equal_to(_with("openrouter/z-ai/glm-5.2")))


def test_a_running_model_that_differs_is_listed_too():
    with given(_setup(EXPLICIT_MODEL)) as context:
        _stored(context, running_model=RUNNING_MODEL)

        assert_that(_models_for(context), equal_to(_with("openrouter/openai/gpt-5-nano", "openrouter/openrouter/free")))


def test_a_starting_model_is_listed_too():
    with given(_setup(EXPLICIT_MODEL)) as context:
        assert_that(
            _models_for(context, STARTING_MODEL),
            equal_to(_with("openrouter/openai/gpt-5-nano", "openrouter/anthropic/claude-sonnet-4.5")),
        )


def test_sync_sets_the_keys_list_from_the_agent_as_stored():
    with given(_setup(EXPLICIT_MODEL)) as context:
        stale = context.injector.get(AgentRepository).get_by_id(context.agent.id)
        _stored(context, model=ORGANIZATION_DEFAULT)
        litellm = context.injector.get(LiteLLMClient)

        with when("the Agent is synced from an object read before its model changed"):
            wrote = context.injector.get(AgentKeyModelService).sync(stale, STARTING_MODEL)

        with then("the key gets the stored Agent's model and the starting model"):
            litellm.set_key_models.assert_called_once_with(
                FAKE_LITELLM_KEY, _with("openrouter/qwen/qwen3.6-plus", "openrouter/anthropic/claude-sonnet-4.5")
            )
            assert_that(wrote, equal_to(False))


def test_sync_by_id_sets_the_keys_list_and_says_whether_it_wrote():
    with given(_setup(EXPLICIT_MODEL)) as context:
        litellm = context.injector.get(LiteLLMClient)
        litellm.set_key_models.return_value = True

        wrote = context.injector.get(AgentKeyModelService).sync_by_id(context.agent.id)

        litellm.set_key_models.assert_called_once_with(FAKE_LITELLM_KEY, _with("openrouter/openai/gpt-5-nano"))
        assert_that(wrote, equal_to(True))


def test_sync_skips_an_agent_without_a_key():
    with given(_setup(EXPLICIT_MODEL)) as context:
        agent = _stored(context, litellm_key_encrypted="")

        wrote = context.injector.get(AgentKeyModelService).sync(agent)

        context.injector.get(LiteLLMClient).set_key_models.assert_not_called()
        assert_that(wrote, equal_to(False))


def test_sync_skips_every_agent_while_litellm_is_not_configured():
    with given(_setup(EXPLICIT_MODEL)) as context:
        context.injector.get(Config).litellm_secret_name = ""
        agent = context.injector.get(AgentRepository).get_by_id(context.agent.id)

        wrote = context.injector.get(AgentKeyModelService).sync(agent)

        context.injector.get(LiteLLMClient).set_key_models.assert_not_called()
        assert_that(wrote, equal_to(False))


def test_the_key_models_lock_is_held_for_the_callback_and_released_after_it():
    with given(_setup()) as context:
        agent_id = context.agent.id
        given_agents = []

        def callback(agent: Agent | None) -> None:
            with pytest.raises(OperationalError, match="lock timeout"):
                _try_lock(context, agent_id)
            given_agents.append(agent.id if agent else None)

        with when("another session tries to take the lock inside the callback"):
            context.injector.get(AgentRepository).with_key_models_lock(agent_id, callback)

        with then("it timed out, and the callback was given the stored Agent"):
            assert_that(given_agents, equal_to([agent_id]))

        with then("after the call another session takes it"):
            _try_lock(context, agent_id)


def test_reconcile_sets_the_list_of_every_live_keyed_agent_in_every_organization():
    with given(
        _setup(
            EXPLICIT_MODEL,
            there_is_an_agent_in_another_org(),
            there_is_an_agent(model=DELETED_MODEL, deleted=True),
            there_is_an_agent(model=KEYLESS_MODEL),
        )
    ) as context:
        _stored(context, litellm_key_encrypted="")

        with when("the sweep runs"):
            context.injector.get(AgentKeyModelService).reconcile()

        with then("the two live keyed Agents get their lists, and the deleted and keyless ones are skipped"):
            assert_that(
                _own_models_synced(context),
                equal_to([["openrouter/openai/gpt-5-nano"], ["openrouter/z-ai/glm-5.2"]]),
            )


def test_reconcile_goes_on_past_a_key_whose_list_cannot_be_set(caplog):
    with given(_setup(FAILING_MODEL)) as context:
        failing_agent_id = context.agent.id
        there_is_an_agent(model=EXPLICIT_MODEL)(context)
        context.injector.get(LiteLLMClient).set_key_models.side_effect = _refuse_failing_model

        with when("the sweep runs and the first key's list can't be set"):
            context.injector.get(AgentKeyModelService).reconcile()

        with then("the next Agent still gets its list, and the failure is logged by Agent id"):
            assert_that(
                _own_models_synced(context),
                equal_to([["openrouter/failing/model"], ["openrouter/openai/gpt-5-nano"]]),
            )
            assert_that(str(failing_agent_id) in caplog.text, equal_to(True))
