from typing import Any
from unittest.mock import Mock
from uuid import uuid7

from api.infrastructure.litellm.decisions import DecisionResult, LiteLLMDecisionClient, YesNoAnswer
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def decisions_api_setup(*steps: Any, env: dict[str, str] | None = None) -> list[Any]:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                **(env or {}),
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        *steps,
    ]


def a_platform_admin_without_membership():
    def step(context):
        organization = context.organization
        del context.organization
        try:
            user_id = uuid7()
            there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
            there_is_an_access_token_for_user(user_id)(context)
        finally:
            context.organization = organization

    return step


def the_decision_model_answers():
    def step(context):
        context.decide = Mock(
            return_value=DecisionResult(answers={"q": YesNoAnswer(0.9)}, input_tokens=10, output_tokens=1)
        )
        context.injector.get(LiteLLMDecisionClient).decide = context.decide

    return step
