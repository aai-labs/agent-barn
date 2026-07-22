from uuid import uuid4

from fastapi import status
from hamcrest import assert_that, equal_to, has_item
from starlette.testclient import TestClient

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
    there_is_a_shared_credential,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template

_AGENTS = "/api/v1/agents"

_JIRA_CONTENT = {
    "site_url": "https://test.atlassian.net",
    "email": "admin@example.com",
    "api_token": "test-jira-token",
}

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
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
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


_VALID_CREATE = {
    "name": "Agent with shared cred",
    "platform": "slack",
    "slack_bot_token": "xoxb-real-bot-token",
    "slack_app_token": "xapp-1-real-app-token",
    "template_slug": "test-template",
}


# --- Create agent with shared credential ---


def test_create_agent_with_shared_credential():
    with given([*_GIVEN, there_is_a_shared_credential()]) as ctx:
        client: TestClient = ctx.client

        with when("I create an agent with a shared credential"):
            payload = {
                **_VALID_CREATE,
                "shared_credentials": [
                    {"shared_credential_id": str(ctx.shared_credential.id)}
                ],
            }
            response = client.post(_AGENTS, json=payload, headers=_auth(ctx))

        with then("it returns 201 with the shared credential in secrets"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            providers = [s["provider"] for s in body["secrets"]]
            assert_that(providers, has_item("jira"))
            jira_secret = next(s for s in body["secrets"] if s["provider"] == "jira")
            assert_that(
                jira_secret["shared_credential_id"],
                equal_to(str(ctx.shared_credential.id)),
            )
            assert_that(jira_secret["shared_credential_name"], equal_to("Shared Jira"))


def test_create_agent_rejects_nonexistent_shared_credential():
    with given(_GIVEN) as ctx:
        client: TestClient = ctx.client

        with when("I create an agent with a nonexistent shared credential"):
            payload = {
                **_VALID_CREATE,
                "shared_credentials": [{"shared_credential_id": str(uuid4())}],
            }
            response = client.post(_AGENTS, json=payload, headers=_auth(ctx))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_rejects_shared_and_manual_same_provider():
    with given([*_GIVEN, there_is_a_shared_credential()]) as ctx:
        client: TestClient = ctx.client

        with when("I create an agent with both shared and manual jira"):
            payload = {
                **_VALID_CREATE,
                "shared_credentials": [
                    {"shared_credential_id": str(ctx.shared_credential.id)}
                ],
                "secrets": [{"provider": "jira", "content": _JIRA_CONTENT}],
            }
            response = client.post(_AGENTS, json=payload, headers=_auth(ctx))

        with then("it returns 422 (duplicate provider)"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


# --- Update agent: attach shared credential ---


def test_update_agent_attach_shared_credential():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_shared_credential()]) as ctx:
        client: TestClient = ctx.client

        with when("I update the agent to attach a shared credential"):
            response = client.patch(
                f"{_AGENTS}/{ctx.agent.id}",
                json={
                    "shared_credentials": [
                        {"shared_credential_id": str(ctx.shared_credential.id)}
                    ],
                },
                headers=_auth(ctx),
            )

        with then("it returns 200 with the shared credential attached"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            providers = [s["provider"] for s in body["secrets"]]
            assert_that(providers, has_item("jira"))
            jira_secret = next(s for s in body["secrets"] if s["provider"] == "jira")
            assert_that(
                jira_secret["shared_credential_id"],
                equal_to(str(ctx.shared_credential.id)),
            )


# --- Update agent: detach shared credential via removed_secret_providers ---


def test_update_agent_detach_shared_credential():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_shared_credential()]) as ctx:
        client: TestClient = ctx.client

        with when("I attach then detach a shared credential"):
            client.patch(
                f"{_AGENTS}/{ctx.agent.id}",
                json={
                    "shared_credentials": [
                        {"shared_credential_id": str(ctx.shared_credential.id)}
                    ],
                },
                headers=_auth(ctx),
            )
            response = client.patch(
                f"{_AGENTS}/{ctx.agent.id}",
                json={"removed_secret_providers": ["jira"]},
                headers=_auth(ctx),
            )

        with then("the jira secret is removed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            providers = [s["provider"] for s in body["secrets"]]
            assert "jira" not in providers
