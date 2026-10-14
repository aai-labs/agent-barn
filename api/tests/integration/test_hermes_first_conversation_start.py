from unittest.mock import MagicMock

import yaml
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, is_not
from starlette.testclient import TestClient

from api.domains.agents.models import AgentType
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.templates.service import TemplateService
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
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
]


def _user_context(context) -> CurrentUserContext:
    return CurrentUserContext(
        user=context.user,
        organization_ids=[context.organization.id],
        user_organization_map={context.organization.id: context.organization_user},
        current_user_organization=context.organization_user,
    )


def _start(context, agent_id) -> int:
    client: TestClient = context.client
    return client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{agent_id}/start",
        headers={"Authorization": f"Bearer {context.access_token}"},
    ).status_code


def _created(context) -> tuple[dict, dict]:
    config_map = context.injector.get(KubernetesClient).create_config_map.call_args.args[1].data
    return config_map, yaml.safe_load(config_map["hermes-config.yaml"])


def test_a_hermes_agent_with_a_real_script_ships_it_and_switches_the_plugin_on():
    with given(_GIVEN) as context:
        context.injector.get(TemplateService).seed_predefined_templates()
        agent = context.injector.get(AgentService).create_onboarding_agent("Ava the Assistant", _user_context(context))

        with when("the onboarding Agent starts"):
            started = _start(context, agent.id)

        with then("its ConfigMap carries the script and its Hermes config enables the plugin"):
            assert_that(started, equal_to(status.HTTP_200_OK))
            config_map, hermes_config = _created(context)
            assert_that(config_map["BOOTSTRAP.md"], contains_string("First conversation"))
            assert_that(hermes_config["plugins"]["enabled"], has_item("agentbarn-first-conversation"))
            assert_that(hermes_config["onboarding"], equal_to({"profile_build": "off"}))


def test_a_hermes_agent_with_a_placeholder_script_starts_exactly_as_before():
    with given([*_GIVEN, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("an Agent on a template with the default bootstrap.md starts"):
            started = _start(context, context.agent.id)

        with then("no script ships and the plugin and Hermes onboarding settings are untouched"):
            assert_that(started, equal_to(status.HTTP_200_OK))
            assert_that(k8s.create_config_map.called, equal_to(True))
            config_map, hermes_config = _created(context)
            assert "BOOTSTRAP.md" not in config_map
            assert_that(hermes_config["plugins"]["enabled"], is_not(has_item("agentbarn-first-conversation")))
            assert "onboarding" not in hermes_config
