"""Trial onboarding (AF-368): a new user's Hermes Agent, with its Agent Barn Telegram
Connection, is set up and started for them; finishing onboarding sends returning users
straight to the dashboard."""

import logging
from unittest.mock import MagicMock

from fastapi import status
from hamcrest import assert_that, equal_to, has_entries, has_length, none, not_none

from api.core.config import Config
from api.domains.agents.models import AgentStatus, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.onboarding.service import OnboardingService
from api.domains.templates.service import TemplateService
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import WEB_APP_URL, FakeGoogleIdentityModule, finish_google_sign_in
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user

ONBOARDING = "/api/v1/onboarding"


def _setup(*steps):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "SELF_SIGNUP_ENABLED": "true",
                "TRIAL_DEFAULT_CREDIT_USD": "10",
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
                "COMMUNICATIONS_BASE_URL": "http://communications.test:8002/communications/v1",
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        predefined_templates_are_seeded(),
        *steps,
    ]


def predefined_templates_are_seeded():
    def step(context):
        context.injector.get(TemplateService).seed_predefined_templates()

    return step


def someone_signed_up_with_google():
    def step(context):
        finish_google_sign_in(context)
        context.access_token = context.client.post("/api/v1/auth/refresh").json()["access_token"]

    return step


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _set_up_agent(context):
    return context.client.post(f"{ONBOARDING}/agent", headers=auth(context))


def _connections(context, onboarding: dict) -> list[dict]:
    response = context.client.get(
        f"/api/v1/organizations/{onboarding['organization_id']}/agents/{onboarding['agent_id']}/connections",
        headers=auth(context),
    )
    return response.json()


def test_a_new_trial_user_has_onboarding_to_do():
    with given(_setup(someone_signed_up_with_google())) as context:
        with when("they open onboarding"):
            response = context.client.get(ONBOARDING, headers=auth(context))

        with then("it is required, for their trial with its credit, and no Agent yet"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                has_entries(
                    required=True,
                    organization_id=not_none(),
                    credit_usd=10.0,
                    agent_id=none(),
                    telegram_bot_username="AgentBarnTestBot",
                ),
            )


def test_setting_up_creates_and_starts_a_hermes_agent():
    with given(_setup(someone_signed_up_with_google())) as context:
        with when("onboarding sets up their Agent"):
            response = _set_up_agent(context)

        with then("a General Purpose Hermes Agent with a suggested name exists and has been started"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(body["agent_name"].endswith(" the Assistant"), equal_to(True), body["agent_name"])
            agent = context.injector.get(AgentRepository).get_by_id(body["agent_id"])
            assert_that(agent.agent_type, equal_to(AgentType.HERMES))
            assert_that(agent.status, equal_to(AgentStatus.RUNNING))
            assert_that(body["agent_status"], equal_to(AgentStatus.RUNNING.value))

        with then("its Deployment was created"):
            k8s: MagicMock = context.injector.get(KubernetesClient)
            assert_that(k8s.create_deployment.call_count, equal_to(1))


def test_setting_up_gives_the_agent_an_agent_barn_telegram_connection():
    with given(_setup(someone_signed_up_with_google())) as context:
        body = _set_up_agent(context).json()

        connections = _connections(context, body)

        assert_that(connections, has_length(1))
        assert_that(connections[0], has_entries(platform_key="agentbarn_telegram", enabled=True))
        assert_that(body["connection_id"], equal_to(connections[0]["id"]))


def test_setting_up_twice_keeps_the_one_agent_and_connection():
    with given(_setup(someone_signed_up_with_google())) as context:
        first = _set_up_agent(context).json()

        with when("onboarding is reopened and asks again"):
            second = _set_up_agent(context)

        with then("the same Agent and Connection are returned, and nothing new is made"):
            assert_that(second.status_code, equal_to(status.HTTP_200_OK), second.text)
            assert_that(second.json(), has_entries(agent_id=first["agent_id"], connection_id=first["connection_id"]))
            assert_that(_connections(context, first), has_length(1))
            agents = context.injector.get(AgentRepository).count_active_by_org(first["organization_id"])
            assert_that(agents, equal_to(1))


def test_an_agent_that_failed_to_start_is_started_again():
    with given(_setup(someone_signed_up_with_google())) as context:
        k8s: MagicMock = context.injector.get(KubernetesClient)
        k8s.create_deployment.side_effect = RuntimeError("cluster unavailable")
        failed = _set_up_agent(context).json()
        assert_that(failed["agent_status"], equal_to(AgentStatus.ERROR.value))

        with when("the cluster recovers and onboarding retries"):
            k8s.create_deployment.side_effect = None
            retried = _set_up_agent(context)

        with then("the same Agent has been started"):
            assert_that(retried.json()["agent_id"], equal_to(failed["agent_id"]))
            assert_that(retried.json()["agent_status"], equal_to(AgentStatus.RUNNING.value))


def test_finishing_onboarding_is_remembered():
    with given(_setup(someone_signed_up_with_google())) as context:
        _set_up_agent(context)

        with when("they finish onboarding"):
            response = context.client.post(f"{ONBOARDING}/complete", headers=auth(context))

        with then("it is no longer required"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            read = context.client.get(ONBOARDING, headers=auth(context)).json()
            assert_that(read, has_entries(required=False, completed_at=not_none()))


def test_after_onboarding_nothing_more_is_set_up():
    with given(_setup(someone_signed_up_with_google())) as context:
        _set_up_agent(context)
        context.client.post(f"{ONBOARDING}/complete", headers=auth(context))

        response = _set_up_agent(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_users_brought_in_by_an_administrator_have_no_onboarding():
    with given(_setup(there_is_an_organization_with_user_and_access_token())) as context:
        with when("they open onboarding"):
            read = context.client.get(ONBOARDING, headers=auth(context))
            set_up = _set_up_agent(context)

        with then("it is not required, and there is nothing to set up"):
            assert_that(read.json(), has_entries(required=False, organization_id=none()))
            assert_that(set_up.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_onboarding_requires_a_signed_in_user():
    with given(_setup()) as context:
        assert_that(context.client.get(ONBOARDING).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_connection_made_by_a_concurrent_setup_is_reused():
    """Two setups racing: the slower one finds the Connection gone missing from its view
    only because the other created it in between. It reuses that one instead of failing."""
    with given(_setup(someone_signed_up_with_google())) as context:
        first = _set_up_agent(context).json()
        service = context.injector.get(OnboardingService)
        original = service._telegram_connection
        calls = []

        def stale_then_fresh(agent_id, trial):
            calls.append(agent_id)
            return None if len(calls) == 1 else original(agent_id, trial)

        service._telegram_connection = stale_then_fresh
        try:
            with when("the second setup only sees no Connection, then hits the first one's"):
                second = _set_up_agent(context)
        finally:
            service._telegram_connection = original

        with then("it reuses the Connection that exists"):
            assert_that(second.status_code, equal_to(status.HTTP_200_OK), second.text)
            assert_that(second.json()["connection_id"], equal_to(first["connection_id"]))


def test_a_running_agent_given_a_new_connection_is_restarted_with_it():
    """The runtime picks up its Connections when it starts, so a running Agent that gets
    its Telegram Connection back must start again to use it."""
    with given(_setup(someone_signed_up_with_google())) as context:
        first = _set_up_agent(context).json()
        revision = _connections(context, first)[0]["revision"]
        deleted = context.client.delete(
            f"/api/v1/organizations/{first['organization_id']}/agents/{first['agent_id']}"
            f"/connections/{first['connection_id']}",
            params={"revision": revision},
            headers=auth(context),
        )
        assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT), deleted.text)
        k8s: MagicMock = context.injector.get(KubernetesClient)
        starts_before = k8s.create_deployment.call_count

        with when("onboarding sets up again while the Agent is running"):
            again = _set_up_agent(context).json()

        with then("a new Connection exists and the Agent was started again with it"):
            assert_that(again["connection_id"], not_none())
            assert_that(again["agent_status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(k8s.create_deployment.call_count, equal_to(starts_before + 1))


def test_a_setup_that_cannot_succeed_says_why_and_is_logged(caplog):
    """Agent Barn's bot was taken away after this user signed up: their Agent can't get its
    Telegram Connection, and they should see why rather than a retry that never works."""
    with given(_setup(someone_signed_up_with_google())) as context:
        context.injector.get(Config).agentbarn_telegram_bot_token = ""

        with when("onboarding sets up their Agent"), caplog.at_level(logging.WARNING):
            response = _set_up_agent(context)

        with then("the reason is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST), response.text)
            assert_that(response.json(), has_entries(detail="Agent Barn Telegram is not available"))

        with then("and logged"):
            assert_that(
                any("Agent Barn Telegram is not available" in record.getMessage() for record in caplog.records),
                equal_to(True),
                caplog.text,
            )


def test_onboarding_follows_the_trials_first_agent():
    """With a trial agent limit above one, the user may hire more; onboarding keeps to the
    Agent it set up, which is the trial's oldest."""
    with given(_setup(someone_signed_up_with_google())) as context:
        first = _set_up_agent(context).json()
        there_is_a_user(email="limit-admin@example.com", is_platform_admin=True, organization_id=None)(context)
        context.injector.get(TrialSettingsRepository).set_settings(
            {"agent_limit": 2}, 10, context.user.id, "Platform Admin"
        )
        hired = context.client.post(
            f"/api/v1/organizations/{first['organization_id']}/agents",
            json={"name": "Aardvark", "template_key": "general-purpose"},
            headers=auth(context),
        )
        assert_that(hired.status_code, equal_to(status.HTTP_201_CREATED), hired.text)

        with when("they open onboarding again"):
            response = context.client.get(ONBOARDING, headers=auth(context))

        with then("it is still about the Agent it set up"):
            assert_that(response.json(), has_entries(agent_id=first["agent_id"]))
