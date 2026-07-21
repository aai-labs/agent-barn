import json
from unittest.mock import patch

import httpx
from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_key,
    is_not,
    none,
)
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.templates.repository import TemplateRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.domains.agents.models import AgentPlatform, AgentType, SecretProvider
from api.domains.agents.service import AgentService
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    skill_is_assigned_to_agent,
    there_is_an_agent,
    there_is_a_skill,
    there_is_a_skill_for_another_org,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template, there_is_a_template_skill

_BASE = "/api/v1/agents"

_VALID_CREATE = {
    "name": "My Agent",
    "platform": "slack",
    "slack_bot_token": "xoxb-real-bot-token",
    "slack_app_token": "xapp-1-real-app-token",
    "template_slug": "test-template",
}

_VALID_CREATE_TEAMS = {
    "name": "My Teams Agent",
    "platform": "teams",
    "teams_app_id": "test-app-id-000",
    "teams_app_password": "test-app-password-000",
    "teams_tenant_id": "test-tenant-000",
    "template_slug": "test-template",
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


def test_create_slack_agent_returns_201_stopped():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Slack agent with valid data"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 with status stopped"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("My Agent"))
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(body, is_not(has_key("slack_bot_token")))
            assert_that(body, is_not(has_key("slack_app_token")))


def test_create_agent_missing_template_slug_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE}
        del payload["template_slug"]

        with when("I create an agent without template_slug"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_agent_unknown_template_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "template_slug": "no-such-template"}

        with when("I create an agent referencing a non-existent template"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without a token"):
            response = client.post(_BASE, json=_VALID_CREATE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_agent_pins_latest_template_version():
    with given(
        [*_GIVEN, there_is_a_template(version=2, soul_md="# Soul v2")]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent referencing a lineage with two versions"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 pinned to the latest version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["template_slug"], equal_to("test-template"))
            assert_that(body["template_version"], equal_to(2))


def test_create_agent_pins_specific_version():
    with given(
        [*_GIVEN, there_is_a_template(version=2, soul_md="# Soul v2")]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent requesting v1 of a two-version lineage"):
            payload = {**_VALID_CREATE, "template_version": 1}
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it pins to the requested version, not the latest"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["template_version"], equal_to(1))


def test_create_agent_unknown_version_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent requesting a non-existent version"):
            payload = {**_VALID_CREATE, "template_version": 99}
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_does_not_create_template_rows():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent from the shared template"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("the lineage still has only its original version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            template_repository: TemplateRepository = context.injector.get(
                TemplateRepository
            )
            latest = template_repository.get_latest_template(
                context.organization.id, "test-template"
            )
            assert_that(latest, is_not(none()))
            assert latest is not None
            assert_that(latest.version, equal_to(1))


def test_create_agent_default_approval_mode_is_auto():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without specifying approval_mode"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("the response has approval_mode set to auto"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("auto"))


def test_create_agent_with_approval_mode_off():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent with approval_mode off"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE, "approval_mode": "off"},
                headers=_auth(context),
            )

        with then("the response has approval_mode set to off"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("off"))


def test_list_agents_returns_active_only():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Active Agent"),
            there_is_an_agent(name="Deleted Agent", deleted=True),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list agents"):
            response = client.get(_BASE, headers=_auth(context))

        with then("only the active agent is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(len(items), equal_to(1))
            assert_that(items[0]["name"], equal_to("Active Agent"))


def test_list_agents_status_filter():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Stopped Agent", status=AgentStatus.STOPPED),
            there_is_an_agent(name="Running Agent", status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I filter by status=RUNNING"):
            response = client.get(f"{_BASE}?status=RUNNING", headers=_auth(context))

        with then("only the running agent is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(len(items), equal_to(1))
            assert_that(items[0]["name"], equal_to("Running Agent"))


def test_list_agents_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list agents without a token"):
            response = client.get(_BASE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_returns_agent():
    with given([*_GIVEN, there_is_an_agent(name="Fetchable Agent")]) as context:
        client: TestClient = context.client

        with when("I get the agent by id"):
            response = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("Fetchable Agent"))


def test_get_deleted_agent_returns_404():
    with given([*_GIVEN, there_is_an_agent(deleted=True)]) as context:
        client: TestClient = context.client

        with when("I get a deleted agent"):
            response = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get an agent without a token"):
            response = client.get(f"{_BASE}/{context.agent.id}")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_patch_agent_updates_name():
    with given([*_GIVEN, there_is_an_agent(name="Old Name")]) as context:
        client: TestClient = context.client

        with when("I patch the agent name"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("New Name"))


def test_patch_agent_repins_template():
    # _GIVEN seeds the "test-template" lineage; the agent has its own generated
    # lineage, so re-pinning to "test-template" v1 is an observable change.
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I re-pin the agent to a different template version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_slug": "test-template", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 200 pinned to the requested template"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["template_slug"], equal_to("test-template"))
            assert_that(body["template_version"], equal_to(1))


def test_patch_agent_repin_unknown_version_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I re-pin to a non-existent version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_slug": "test-template", "template_version": 99},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_repin_requires_both_slug_and_version():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I send only template_slug without a version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_slug": "test-template"},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_patch_running_agent_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I patch a running agent"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "Should Fail"},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_patch_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch an agent without a token"):
            response = client.patch(f"{_BASE}/{context.agent.id}", json={"name": "X"})

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_patch_agent_approval_mode():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I update the agent's approval_mode to manual"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": "manual"},
                headers=_auth(context),
            )

        with then("the response reflects the new approval_mode"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["approval_mode"], equal_to("manual"))


_JIRA_CONTENT = {
    "site_url": "https://acme.atlassian.net",
    "email": "a@b.com",
    "api_token": "jira-tok",
}


def _providers(response) -> list[str]:
    return [s["provider"] for s in response.json()["secrets"]]


def test_patch_agent_adds_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a jira secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the jira secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["jira"]))
            jira = response.json()["secrets"][0]
            assert_that(jira["secret_name"], equal_to("Jira credential"))


def test_patch_agent_upserts_existing_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        repository: AgentRepository = context.injector.get(AgentRepository)

        with when("I patch the same provider twice with different content"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "jira",
                            "content": {**_JIRA_CONTENT, "api_token": "new-tok"},
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("there is exactly one jira row (upsert, not duplicate)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            rows = repository.get_secrets_for_agent(context.agent.id)
            jira_rows = [r for r in rows if r.provider == SecretProvider.JIRA]
            assert_that(len(jira_rows), equal_to(1))


def test_patch_agent_removes_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I add then remove a jira secret"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_secret_providers": ["jira"]},
                headers=_auth(context),
            )

        with then("the jira secret is gone"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to([]))


def test_patch_running_agent_with_secret_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I patch a running agent with a secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_patch_agent_secret_in_both_lists_returns_422():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch with a provider in both secrets and removed lists"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [{"provider": "jira", "content": _JIRA_CONTENT}],
                    "removed_secret_providers": ["jira"],
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_patch_agent_invalid_secret_content_returns_422():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch with jira content missing api_token"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {"provider": "jira", "content": {"site_url": "x", "email": "y"}}
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


# --- optional/multi repos for GitHub and Bitbucket secrets (AF-162) ---

_GITHUB_CONTENT_NO_REPOS = {
    "token": "ghp_token",
    "owner": "my-org",
    "org": "my-org",
}

_BITBUCKET_CONTENT_NO_REPOS = {
    "workspace": "my-workspace",
    "email": "a@b.com",
    "api_token": "bb-tok",
}


def test_patch_agent_adds_github_secret_without_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a GitHub secret and no repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {"provider": "github", "content": _GITHUB_CONTENT_NO_REPOS}
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the github secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["github"]))


def test_patch_agent_adds_github_secret_with_multiple_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a GitHub secret listing multiple repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "github",
                            "content": {
                                **_GITHUB_CONTENT_NO_REPOS,
                                "repos": ["repo-a", "repo-b"],
                            },
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the github secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["github"]))


def test_patch_agent_adds_bitbucket_secret_without_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a Bitbucket secret and no repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "bitbucket",
                            "content": _BITBUCKET_CONTENT_NO_REPOS,
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the bitbucket secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["bitbucket"]))


def test_patch_agent_adds_bitbucket_secret_with_multiple_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a Bitbucket secret listing multiple repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "bitbucket",
                            "content": {
                                **_BITBUCKET_CONTENT_NO_REPOS,
                                "repos": ["repo-a", "repo-b"],
                            },
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the bitbucket secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["bitbucket"]))


def test_validate_integration_with_no_repos_returns_valid():
    """A credential with zero configured repos is a legitimate config — the validate
    endpoint must not report it as invalid."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={
                "secrets": [{"provider": "github", "content": _GITHUB_CONTENT_NO_REPOS}]
            },
            headers=_auth(context),
        )

        user_resp = httpx.Response(
            200,
            json={"login": "alice"},
            request=httpx.Request("GET", "https://api.github.com/user"),
        )

        with when("I validate the GitHub integration"):
            with patch(
                "api.infrastructure.integration_validators.github.httpx.get",
                return_value=user_resp,
            ):
                response = client.post(
                    f"{_BASE}/{context.agent.id}/integrations/github/validate",
                    headers=_auth(context),
                )

        with then(
            "it returns a valid status, not invalid, despite no repos configured"
        ):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["validation_status"], equal_to("valid"))


def test_start_agent_sets_status_running():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("it returns 200 with status RUNNING and k8s resources are created"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.RUNNING.value))
            k8s.delete_config_map.assert_called_once()
            k8s.delete_secret.assert_called_once()
            k8s.create_config_map.assert_called_once()
            k8s.create_secret.assert_called_once()
            k8s.create_pvc.assert_called_once()
            k8s.create_service.assert_called_once()
            k8s.create_deployment.assert_called_once()


def test_start_already_running_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I start an already running agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_start_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I start an agent without a token"):
            response = client.post(f"{_BASE}/{context.agent.id}/start")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_stop_agent_sets_status_stopped():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I stop the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/stop", headers=_auth(context)
            )

        with then("it returns 200 with status STOPPED and deployment is deleted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.STOPPED.value))
            k8s.delete_deployment.assert_called_once()


def test_stop_non_running_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client

        with when("I stop a non-running agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/stop", headers=_auth(context)
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_stop_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I stop an agent without a token"):
            response = client.post(f"{_BASE}/{context.agent.id}/stop")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_delete_agent_soft_deletes():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("I delete the agent"):
            response = client.delete(f"{_BASE}/{agent_id}", headers=_auth(context))

        with then("it returns 204 and the agent has deleted_at set"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

            repository: AgentRepository = context.injector.get(AgentRepository)
            from sqlmodel import Session, col, select
            from api.domains.agents.models import Agent

            with Session(repository.delegate.engine) as session:
                agent = session.exec(
                    select(Agent).where(col(Agent.id) == agent_id)
                ).first()
            assert agent is not None
            assert_that(agent.deleted_at, is_not(none()))


def test_delete_agent_removes_all_k8s_resources():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I delete a running agent"):
            response = client.delete(
                f"{_BASE}/{context.agent.id}", headers=_auth(context)
            )

        with then("it returns 204 and all k8s resources were deleted"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            k8s.delete_deployment.assert_called_once()
            k8s.delete_service.assert_called_once()
            k8s.delete_pvc.assert_called_once()
            k8s.delete_secret.assert_called_once()
            k8s.delete_config_map.assert_called_once()


def test_delete_stopped_agent_still_removes_deployment():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.STOPPED),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I delete a stopped agent"):
            response = client.delete(
                f"{_BASE}/{context.agent.id}", headers=_auth(context)
            )

        with then("it returns 204 and delete_deployment was still called"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            k8s.delete_deployment.assert_called_once()


def test_deleted_agent_not_in_list():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I delete the agent then list agents"):
            client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))
            response = client.get(_BASE, headers=_auth(context))

        with then("the list is empty"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["items"], equal_to([]))


def test_delete_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I delete an agent without a token"):
            response = client.delete(f"{_BASE}/{context.agent.id}")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_agent_calls_litellm_generate_key():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)

        with when("I create an agent"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("LiteLLM generate_key was called once"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            agent_id = response.json()["id"]
            # the test uses _VALID_CREATE where name is "Test Agent"
            litellm.generate_key.assert_called_once_with(
                agent_id, _VALID_CREATE["name"], str(context.organization.id)
            )


def test_create_agent_litellm_failure_returns_503():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        litellm.generate_key.side_effect = LiteLLMError("down")

        with when("I create an agent but LiteLLM is down"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 503 and no agent was saved"):
            assert_that(
                response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE)
            )
            repository: AgentRepository = context.injector.get(AgentRepository)
            from api.domains.agents.models import AgentFilter
            from api.domains.rbac.policy import AuthorizationScope
            from api.infrastructure.shared.models import Pagination

            _, total = repository.find_all_active(
                AuthorizationScope(organization_id=context.organization.id),
                AgentFilter(),
                Pagination(page=1, size=10),
            )
            assert_that(total, equal_to(0))


def test_start_agent_injects_per_agent_key():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the secret is created with the per-agent LiteLLM key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            call_kwargs = k8s.create_secret.call_args
            secret = call_kwargs.args[1]
            assert_that(
                secret.string_data["LITELLM_API_KEY"], equal_to(FAKE_LITELLM_KEY)
            )


def test_delete_agent_calls_litellm_block_key():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)

        with when("I delete the agent"):
            response = client.delete(
                f"{_BASE}/{context.agent.id}", headers=_auth(context)
            )

        with then("LiteLLM block_key was called once"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            litellm.block_key.assert_called_once_with(FAKE_LITELLM_KEY)


def test_delete_agent_litellm_failure_still_returns_204():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        litellm.block_key.side_effect = Exception("timeout")

        with when("I delete the agent but LiteLLM key revocation fails"):
            response = client.delete(
                f"{_BASE}/{context.agent.id}", headers=_auth(context)
            )

        with then("it still returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_create_agent_with_model():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "model": "litellm/gpt-5"}

        with when("I create an agent with a model"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 with the model set"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["model"], equal_to("litellm/gpt-5"))


def test_create_agent_without_model_defaults_to_empty():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without specifying model"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 with model as empty string"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["model"], equal_to(""))


def test_patch_agent_updates_model():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent model"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"model": "litellm/gpt-5"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["model"], equal_to("litellm/gpt-5"))


def test_start_agent_configmap_has_overlay():
    with given([*_GIVEN, there_is_an_agent(model="litellm/gpt-5")]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap contains the overlay with the correct model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            import json

            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(
                overlay["agents"]["defaults"]["model"]["primary"],
                equal_to("litellm/gpt-5"),
            )
            assert_that(
                overlay["models"]["providers"]["litellm"]["baseUrl"],
                equal_to("http://litellm:4000"),
            )


def test_start_agent_configmap_has_init_script():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap contains the init script"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("init-openclaw.js"))


def test_start_agent_init_script_does_not_copy_whole_openclaw_npm_tree():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Slack agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the init script does not restore Teams plugins for every agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            init_js = config_map.data["init-openclaw.js"]
            assert_that(
                init_js,
                is_not(
                    contains_string("fs.cpSync(PREINSTALLED_NPM_DIR, RUNTIME_NPM_DIR")
                ),
            )
            assert_that(
                init_js,
                contains_string(
                    "getPath(overlay, ['channels', 'msteams', 'enabled']) !== true"
                ),
            )


def test_start_agent_deployment_runs_init_script():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the Deployment command runs start.sh"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            deployment = k8s.create_deployment.call_args.args[1]
            command = deployment.spec.template.spec.containers[0].command
            assert_that(command, equal_to(["sh", "/app/config/start.sh"]))


def test_start_agent_uses_default_model_when_empty():
    with given([*_GIVEN, there_is_an_agent(model="")]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start an agent with no model set"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the overlay uses the default model from config"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            import json

            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(
                overlay["agents"]["defaults"]["model"]["primary"],
                equal_to("litellm/gpt-5-mini"),
            )


def test_pair_slack_agent_returns_400():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I pair a Slack agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_pair_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I pair an agent without a token"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
            )

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_template_returns_template():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get the agent's template"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/1",
                headers=_auth(context),
            )

        with then("it returns 200 with the full template"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(1))
            assert_that(body["soul_md"], equal_to("# Soul\n\nTest soul."))
            assert_that(body["identity_md"], equal_to("# Identity\n\nTest identity."))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))
            assert_that(body, has_key("created_at"))
            assert_that(body, has_key("updated_at"))


def test_get_template_missing_version_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I request a non-existent template version"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/99",
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_template_for_deleted_agent_returns_404():
    with given([*_GIVEN, there_is_an_agent(deleted=True)]) as context:
        client: TestClient = context.client

        with when("I get the template of a deleted agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/1",
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_agent_template_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get a template without a token"):
            response = client.get(f"{_BASE}/{context.agent.id}/template/1")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_start_agent_configmap_and_overlay_are_correct():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        import json

        config_map = k8s.create_config_map.call_args.args[1]
        overlay = json.loads(config_map.data["openclaw-config-overlay.json"])

        with then(
            "the overlay configures the slack channel with default allowlist groups + DMs off"
        ):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            slack = overlay["channels"]["slack"]
            assert_that(slack["mode"], equal_to("socket"))
            assert_that(slack["enabled"], equal_to(True))
            assert_that(slack["groupPolicy"], equal_to("allowlist"))
            assert_that(slack["dmPolicy"], equal_to("allowlist"))
            assert_that(slack["userTokenReadOnly"], equal_to(True))
            assert_that(slack["allowFrom"], equal_to([]))
            assert_that(
                slack["replyToModeByChatType"],
                equal_to({"direct": "off", "group": "all", "channel": "all"}),
            )
            assert_that(
                slack["streaming"],
                equal_to({"mode": "partial", "nativeTransport": True}),
            )

        with then("the overlay routes the slack channel to the main agent"):
            bindings = overlay["bindings"]
            assert_that(len(bindings), equal_to(1))
            assert_that(bindings[0]["type"], equal_to("route"))
            assert_that(bindings[0]["agentId"], equal_to("main"))
            assert_that(bindings[0]["match"]["channel"], equal_to("slack"))

        with then("tools, memory, and the core/active-memory plugins are enabled"):
            assert_that(overlay["tools"]["profile"], equal_to("full"))
            assert_that(overlay["memory"]["backend"], equal_to("builtin"))
            assert_that(overlay["plugins"]["slots"]["memory"], equal_to("memory-core"))
            assert_that(
                overlay["plugins"]["entries"]["memory-core"]["enabled"], equal_to(True)
            )
            assert_that(
                overlay["plugins"]["entries"]["active-memory"]["enabled"],
                equal_to(True),
            )

        with then("the ConfigMap contains all 8 template markdown files"):
            for key in (
                "SOUL.md",
                "IDENTITY.md",
                "USER.md",
                "TOOLS.md",
                "AGENTS.md",
                "BOOT.md",
                "BOOTSTRAP.md",
                "HEARTBEAT.md",
            ):
                assert_that(config_map.data, has_key(key))

        with then("soul_md and identity_md in the ConfigMap match the template"):
            assert_that(config_map.data["SOUL.md"], equal_to("# Soul\n\nTest soul."))
            assert_that(
                config_map.data["IDENTITY.md"], equal_to("# Identity\n\nTest identity.")
            )


def test_start_agent_renders_template_placeholders():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(
                name="Maya Bot",
                soul_md="# Soul of {{ agent_display_name }} ({{agent_name}})",
                tools_md="# Tools for {{ unknown_placeholder }}",
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        config_map = k8s.create_config_map.call_args.args[1]

        with then("known placeholders are rendered from the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                config_map.data["SOUL.md"],
                equal_to("# Soul of Maya Bot (maya-bot)"),
            )

        with then("unknown placeholders pass through"):
            tools = config_map.data["TOOLS.md"]
            assert_that(tools, contains_string("{{ unknown_placeholder }}"))

        with then("the stored template keeps its raw placeholders"):
            template_repository: TemplateRepository = context.injector.get(
                TemplateRepository
            )
            stored = template_repository.get_template_or_raise(
                context.organization.id,
                context.agent.template_slug,
                context.agent.template_version,
            )
            assert_that(
                stored.soul_md,
                equal_to("# Soul of {{ agent_display_name }} ({{agent_name}})"),
            )


def test_get_agent_healthz_returns_ok_when_healthy():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the pod /healthz returns healthy"):
            with patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("ready", None),
            ):
                with patch.object(
                    context.injector.get(KubernetesClient),
                    "fetch_agent_healthz",
                    return_value={"status": "ok"},
                ):
                    response = client.get(
                        f"{_BASE}/{agent_id}/healthz", headers=_auth(context)
                    )

        with then("the API returns 200 with status ok"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("ok"))


def test_get_agent_healthz_returns_503_when_pod_unreachable():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the pod is unreachable"):
            with patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("ready", None),
            ):
                with patch.object(
                    context.injector.get(KubernetesClient),
                    "fetch_agent_healthz",
                    side_effect=RuntimeError("connection refused"),
                ):
                    response = client.get(
                        f"{_BASE}/{agent_id}/healthz", headers=_auth(context)
                    )

        with then("the API returns 503"):
            assert_that(
                response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE)
            )


def test_get_agent_healthz_returns_initializing_when_pod_not_ready():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the pod is running but not yet ready"):
            with patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("initializing", None),
            ):
                response = client.get(
                    f"{_BASE}/{agent_id}/healthz", headers=_auth(context)
                )

        with then("the API returns 200 with status initializing"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("initializing"))


def test_get_agent_healthz_returns_crashed_when_pod_has_crashed():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the pod is in CrashLoopBackOff"):
            with patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("crashed", "CrashLoopBackOff"),
            ):
                response = client.get(
                    f"{_BASE}/{agent_id}/healthz", headers=_auth(context)
                )

        with then("the API returns 200 with status crashed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("crashed"))


def test_get_agent_healthz_returns_409_when_agent_not_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the agent is stopped"):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_agent_with_slack_settings():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE,
            "slack_channel_ids": ["C111", "C222"],
            "slack_dm_user_ids": ["U001"],
            "slack_group_policy": "allowlist",
            "slack_dm_policy": "allowlist",
            "slack_verbose_mode": False,
        }

        with when("I create an agent with Slack settings"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 with the Slack settings"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["slack_config"]["channel_ids"], equal_to(["C111", "C222"]))
            assert_that(body["slack_config"]["dm_user_ids"], equal_to(["U001"]))
            assert_that(body["slack_config"]["group_policy"], equal_to("allowlist"))
            assert_that(body["slack_config"]["dm_policy"], equal_to("allowlist"))
            assert_that(body["slack_config"]["verbose_mode"], equal_to(False))


def test_create_agent_defaults_to_allowlist_groups_dms_off():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without specifying Slack policies"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it defaults to allowlist group policy and DMs off"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["slack_config"]["group_policy"], equal_to("allowlist"))
            assert_that(body["slack_config"]["dm_policy"], equal_to("off"))
            assert_that(body["slack_config"]["channel_ids"], equal_to([]))
            assert_that(body["slack_config"]["dm_user_ids"], equal_to([]))
            assert_that(body["slack_config"]["verbose_mode"], equal_to(True))


def test_patch_agent_updates_slack_settings():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent's Slack settings"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "slack_channel_ids": ["C999"],
                    "slack_dm_user_ids": ["U888"],
                    "slack_group_policy": "open",
                    "slack_dm_policy": "allowlist",
                    "slack_verbose_mode": False,
                },
                headers=_auth(context),
            )

        with then("it returns 200 with the updated Slack settings"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["slack_config"]["channel_ids"], equal_to(["C999"]))
            assert_that(body["slack_config"]["dm_user_ids"], equal_to(["U888"]))
            assert_that(body["slack_config"]["group_policy"], equal_to("open"))
            assert_that(body["slack_config"]["dm_policy"], equal_to("allowlist"))
            assert_that(body["slack_config"]["verbose_mode"], equal_to(False))


def test_start_agent_overlay_uses_slack_settings():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={
                "slack_channel_ids": ["C123"],
                "slack_dm_user_ids": ["U456"],
                "slack_group_policy": "allowlist",
                "slack_dm_policy": "allowlist",
            },
            headers=_auth(context),
        )

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the overlay reflects the Slack settings"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            slack = overlay["channels"]["slack"]
            assert_that(slack["groupPolicy"], equal_to("allowlist"))
            assert_that(slack["dmPolicy"], equal_to("allowlist"))
            assert_that(slack["allowFrom"], equal_to(["U456"]))
            assert_that(
                slack["channels"],
                equal_to({"C123": {"enabled": True, "requireMention": True}}),
            )


def test_start_agent_open_policy_sets_allow_from_wildcard():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"slack_dm_policy": "open", "slack_dm_user_ids": []},
            headers=_auth(context),
        )

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("allowFrom defaults to wildcard"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(overlay["channels"]["slack"]["allowFrom"], equal_to(["*"]))


def test_start_agent_off_dm_policy_sets_direct_reply_off():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"slack_dm_policy": "off", "slack_dm_user_ids": ["U999"]},
            headers=_auth(context),
        )

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("DMs are turned off in the overlay and the user list is preserved"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            slack = overlay["channels"]["slack"]
            assert_that(slack["replyToModeByChatType"]["direct"], equal_to("off"))
            assert_that(slack["allowFrom"], equal_to([]))
            assert_that(slack["dmPolicy"], equal_to("allowlist"))


def test_start_agent_allowlist_with_no_users_sets_empty_allow_from():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"slack_dm_policy": "allowlist", "slack_dm_user_ids": []},
            headers=_auth(context),
        )

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("allowFrom is empty — no one can DM"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(overlay["channels"]["slack"]["allowFrom"], equal_to([]))

        with then("the init script syncs slack-allowFrom.json from the overlay"):
            init_js = config_map.data["init-openclaw.js"]
            assert_that(init_js, contains_string("slack-allowFrom.json"))


def test_list_slack_channels_returns_filtered_list():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        slack_response = {
            "ok": True,
            "channels": [
                {"id": "C001", "name": "general"},
                {"id": "C002", "name": "engineering"},
                {"id": "C003", "name": "random"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        with patch("httpx.request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json=slack_response,
                request=httpx.Request("GET", "https://slack.com/api/test"),
            )

            with when("I list Slack channels with a search query"):
                response = client.get(
                    f"{_BASE}/{context.agent.id}/slack/channels?search=eng",
                    headers=_auth(context),
                )

        with then("it returns only matching channels"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            results = response.json()
            assert_that(len(results), equal_to(1))
            assert_that(results[0]["id"], equal_to("C002"))
            assert_that(results[0]["name"], equal_to("engineering"))


def test_list_slack_users_excludes_bots_and_deleted():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        slack_response = {
            "ok": True,
            "members": [
                {
                    "id": "U001",
                    "name": "alice",
                    "real_name": "Alice Smith",
                    "deleted": False,
                    "is_bot": False,
                },
                {
                    "id": "U002",
                    "name": "bob",
                    "real_name": "Bob Jones",
                    "deleted": True,
                    "is_bot": False,
                },
                {
                    "id": "U003",
                    "name": "mybot",
                    "real_name": "My Bot",
                    "deleted": False,
                    "is_bot": True,
                },
            ],
            "response_metadata": {"next_cursor": ""},
        }

        with patch("httpx.request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json=slack_response,
                request=httpx.Request("GET", "https://slack.com/api/test"),
            )

            with when("I list Slack users"):
                response = client.get(
                    f"{_BASE}/{context.agent.id}/slack/users",
                    headers=_auth(context),
                )

        with then("only non-deleted, non-bot users are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            results = response.json()
            assert_that(len(results), equal_to(1))
            assert_that(results[0]["id"], equal_to("U001"))


def test_create_teams_agent_returns_201_and_starts_agent():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Teams agent with valid data"):
            response = client.post(
                _BASE, json=_VALID_CREATE_TEAMS, headers=_auth(context)
            )

        with then("it returns 201 with status running and webhook_url"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("My Teams Agent"))
            assert_that(body["platform"], equal_to("teams"))
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["teams_config"]["tenant_id"], equal_to("test-tenant-000"))
            assert_that(body, has_key("webhook_url"))
            assert_that(body["webhook_url"], contains_string("/webhooks/teams/"))
            assert_that(body["slack_config"], none())


def test_create_teams_agent_missing_credentials_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE_TEAMS}
        del payload["teams_app_password"]

        with when("I create a Teams agent without app_password"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_slack_agent_missing_tokens_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE}
        del payload["slack_bot_token"]

        with when("I create a Slack agent without bot_token"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_start_teams_agent_creates_correct_k8s_resources():
    with given([*_GIVEN, there_is_an_agent(platform=AgentPlatform.TEAMS)]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Teams agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("it returns 200 and K8s resources have Teams config"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data, has_key("MSTEAMS_APP_ID"))
            assert_that(secret.string_data, has_key("MSTEAMS_APP_PASSWORD"))
            assert_that(secret.string_data, has_key("MSTEAMS_TENANT_ID"))

            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(overlay["channels"], has_key("msteams"))
            assert_that(overlay["channels"]["msteams"]["enabled"], equal_to(True))
            init_js = config_map.data["init-openclaw.js"]
            assert_that(init_js, contains_string("PREINSTALLED_MSTEAMS_DIR"))
            assert_that(
                init_js,
                contains_string("Restored preinstalled Microsoft Teams npm plugin"),
            )
            assert_that(init_js, contains_string("package.json"))
            assert_that(init_js, contains_string("package-lock.json"))

            service = k8s.create_service.call_args.args[1]
            ports_by_name = {
                p.name: (p.port, p.target_port) for p in service.spec.ports
            }
            assert_that(ports_by_name["gateway"], equal_to((80, 8080)))
            assert_that(ports_by_name["healthz"], equal_to((8081, 8081)))
            assert_that(ports_by_name["webhook"], equal_to((3978, 3978)))


def test_teams_webhook_relay_proxies_to_pod():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING, platform=AgentPlatform.TEAMS),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.proxy_to_agent.return_value = (
            200,
            b'{"status":"ok"}',
            {"content-type": "application/json"},
        )

        with when("I POST to the Teams webhook"):
            response = client.post(
                f"/api/v1/webhooks/teams/{context.agent.id}/messages",
                content=b'{"type":"message"}',
                headers={"Content-Type": "application/json"},
            )

        with then("it proxies to the pod and returns the response"):
            assert_that(response.status_code, equal_to(200))
            k8s.proxy_to_agent.assert_called_once()


def test_teams_webhook_relay_returns_404_for_slack_agent():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I POST to the Teams webhook for a Slack agent"):
            response = client.post(
                f"/api/v1/webhooks/teams/{context.agent.id}/messages",
                content=b'{"type":"message"}',
                headers={"Content-Type": "application/json"},
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_teams_webhook_relay_returns_503_for_stopped_agent():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.STOPPED, platform=AgentPlatform.TEAMS),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I POST to the Teams webhook for a stopped agent"):
            response = client.post(
                f"/api/v1/webhooks/teams/{context.agent.id}/messages",
                content=b'{"type":"message"}',
                headers={"Content-Type": "application/json"},
            )

        with then("it returns 503"):
            assert_that(
                response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE)
            )


def test_update_teams_agent_rejects_slack_fields():
    with given([*_GIVEN, there_is_an_agent(platform=AgentPlatform.TEAMS)]) as context:
        client: TestClient = context.client

        with when("I patch a Teams agent with Slack-specific fields"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"slack_bot_token": "xoxb-should-fail"},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_pair_teams_agent_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING, platform=AgentPlatform.TEAMS),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I pair a Teams agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


# ---------------------------------------------------------------------------
# Hermes agent tests
# ---------------------------------------------------------------------------

_VALID_CREATE_HERMES = {
    "name": "My Hermes Agent",
    "platform": "slack",
    "agent_type": "hermes",
    "slack_bot_token": "xoxb-hermes-bot-token",
    "slack_app_token": "xapp-1-hermes-app-token",
    "template_slug": "test-template",
}

_GIVEN_WITH_HERMES_IMAGE = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
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


def test_create_hermes_agent_returns_201_stopped():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Hermes Slack agent"):
            response = client.post(
                _BASE, json=_VALID_CREATE_HERMES, headers=_auth(context)
            )

        with then("it returns 201 with agent_type hermes and status stopped"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["agent_type"], equal_to("hermes"))
            assert_that(body["platform"], equal_to("slack"))
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))


def test_create_agent_defaults_to_openclaw_type():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Slack agent without specifying agent_type"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("agent_type defaults to openclaw"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["agent_type"], equal_to("openclaw"))


def test_create_hermes_teams_agent_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE_HERMES,
            "platform": "teams",
            "teams_app_id": "app-id",
            "teams_app_password": "app-pass",
            "teams_tenant_id": "tenant-id",
        }
        del payload["slack_bot_token"]
        del payload["slack_app_token"]

        with when("I create a Hermes agent with Teams platform"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_hermes_agent_missing_slack_tokens_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE_HERMES}
        del payload["slack_bot_token"]

        with when("I create a Hermes agent without slack_bot_token"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_start_hermes_agent_uses_hermes_image_and_config():
    with given(
        [
            *_GIVEN_WITH_HERMES_IMAGE,
            there_is_an_agent(agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("it returns 200 with status RUNNING"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.RUNNING.value))

        with then("the deployment uses the Hermes image"):
            deployment = k8s.create_deployment.call_args.args[1]
            assert_that(
                deployment.spec.template.spec.containers[0].image,
                equal_to("nousresearch/hermes-agent:v1.0"),
            )

        with then("all k8s resources were created"):
            k8s.create_config_map.assert_called_once()
            k8s.create_secret.assert_called_once()
            k8s.create_pvc.assert_called_once()
            k8s.create_service.assert_called_once()
            k8s.create_deployment.assert_called_once()


def test_start_hermes_agent_configmap_has_hermes_config():
    import yaml as _yaml

    with given(
        [*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap contains hermes-config.yaml with correct model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("hermes-config.yaml"))
            cfg = _yaml.safe_load(config_map.data["hermes-config.yaml"])
            assert_that(cfg["model"]["base_url"], equal_to("http://litellm:4000"))
            assert_that(cfg["slack"]["unauthorized_dm_behavior"], equal_to("ignore"))
            assert_that(
                cfg["display"]["platforms"]["slack"]["interim_assistant_messages"],
                equal_to(True),
            )
            assert_that("slack-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))
            assert_that(
                "slack-channel-allowlist" in cfg["plugins"]["enabled"], equal_to(True)
            )

        with then("the ConfigMap has start.sh, healthz sidecar, and both plugins"):
            assert_that(config_map.data, has_key("start.sh"))
            assert_that(config_map.data, has_key("healthz-server.py"))
            assert_that(config_map.data, has_key("slack-deny-dms-plugin.yaml"))
            assert_that(config_map.data, has_key("slack-deny-dms-init.py"))
            assert_that(config_map.data, has_key("slack-channel-allowlist-plugin.yaml"))
            assert_that(config_map.data, has_key("slack-channel-allowlist-init.py"))

        with then("SOUL.md has the bootloader footer appended"):
            soul = config_map.data["SOUL.md"]
            assert_that(soul, contains_string("# Soul\n\nTest soul."))
            assert_that(soul, contains_string("/workspace/IDENTITY.md"))

        with then("BOOTSTRAP.md is absent from the ConfigMap"):
            assert_that(config_map.data, is_not(has_key("BOOTSTRAP.md")))


def test_start_hermes_agent_configmap_concise_mode():
    import yaml as _yaml

    with given(
        [*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"slack_verbose_mode": False},
            headers=_auth(context),
        )

        with when("I start the Hermes agent in concise mode"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("hermes-config.yaml disables interim assistant messages"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            cfg = _yaml.safe_load(config_map.data["hermes-config.yaml"])
            slack_display = cfg["display"]["platforms"]["slack"]
            assert_that(slack_display["interim_assistant_messages"], equal_to(False))
            assert_that(slack_display["busy_ack_detail"], equal_to(False))


def test_start_hermes_agent_secret_has_channel_and_dm_lists():
    with given(
        [
            *_GIVEN_WITH_HERMES_IMAGE,
            there_is_an_agent(agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={
                "slack_channel_ids": ["C001", "C002"],
                "slack_dm_user_ids": ["U001", "U002"],
                "slack_dm_policy": "allowlist",
            },
            headers=_auth(context),
        )

        with when("I start the Hermes agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then(
            "the secret has SLACK_CHANNEL_IDS, SLACK_DM_ALLOWED_USERS, and SLACK_ALLOW_ALL_USERS"
        ):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["SLACK_CHANNEL_IDS"], equal_to("C001,C002"))
            assert_that(
                secret.string_data["SLACK_DM_ALLOWED_USERS"], equal_to("U001,U002")
            )
            assert_that(secret.string_data["SLACK_ALLOW_ALL_USERS"], equal_to("true"))
            assert_that(secret.string_data["API_SERVER_ENABLED"], equal_to("true"))


def test_start_hermes_agent_no_channels_gives_empty_slack_channel_ids():
    with given(
        [*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent with no channel_ids configured"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("SLACK_CHANNEL_IDS is empty — agent responds in all channels"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["SLACK_CHANNEL_IDS"], equal_to(""))


def test_start_hermes_agent_deployment_has_workspace_volume():
    with given(
        [*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the deployment mounts /opt/data and /workspace"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            deployment = k8s.create_deployment.call_args.args[1]
            mounts = {
                m.mount_path
                for m in deployment.spec.template.spec.containers[0].volume_mounts
            }
            assert_that("/opt/data" in mounts, equal_to(True))
            assert_that("/workspace" in mounts, equal_to(True))

        with then("one volume is emptyDir for workspace"):
            from kubernetes.client import V1EmptyDirVolumeSource

            volumes = deployment.spec.template.spec.volumes
            empty_dirs = [
                v for v in volumes if isinstance(v.empty_dir, V1EmptyDirVolumeSource)
            ]
            assert_that(len(empty_dirs), equal_to(1))


def test_pair_hermes_agent_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING, agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I pair a Hermes agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_list_slack_channels_works_for_hermes_agent():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING, agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client

        slack_response = {
            "ok": True,
            "channels": [{"id": "C001", "name": "general"}],
            "response_metadata": {"next_cursor": ""},
        }

        with patch("httpx.request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json=slack_response,
                request=httpx.Request("GET", "https://slack.com/api/test"),
            )

            with when("I list Slack channels for a Hermes agent"):
                response = client.get(
                    f"{_BASE}/{context.agent.id}/slack/channels",
                    headers=_auth(context),
                )

        with then("it returns 200 with channels"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(len(response.json()), equal_to(1))


def test_existing_agent_rows_backfill_to_openclaw():
    with given([*_GIVEN, there_is_an_agent(name="Legacy Agent")]) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)

        with when("I read an agent created without an explicit agent_type"):
            agent = repository.get_active(context.agent.id, context.organization.id)

        with then("agent_type is openclaw (server_default applied)"):
            assert_that(agent.agent_type, equal_to(AgentType.OPENCLAW))


# ---------------------------------------------------------------------------
# Slack token validation — unhappy paths
# ---------------------------------------------------------------------------


def test_create_slack_agent_rejects_invalid_tokens():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with patch.object(
            AgentService,
            "_check_slack_tokens",
            return_value=(False, "Slack bot token is invalid."),
        ):
            with when("I create a Slack agent with invalid tokens"):
                response = client.post(
                    _BASE, json=_VALID_CREATE, headers=_auth(context)
                )

        with then("it returns 400 and no agent is left in the database"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("invalid"))
            list_response = client.get(_BASE, headers=_auth(context))
            assert_that(list_response.json()["total"], equal_to(0))


def test_update_slack_agent_rejects_invalid_tokens():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with patch.object(
            AgentService,
            "_check_slack_tokens",
            return_value=(False, "Slack bot token is invalid."),
        ):
            with when("I patch a Slack agent with invalid tokens"):
                response = client.patch(
                    f"{_BASE}/{context.agent.id}",
                    json={"slack_bot_token": "xoxb-bad"},
                    headers=_auth(context),
                )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("invalid"))


def test_start_slack_agent_with_invalid_tokens_sets_error_status():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with patch.object(
            AgentService,
            "_check_slack_tokens",
            return_value=(False, "Slack bot token is invalid."),
        ):
            with when("I start a Slack agent with invalid tokens"):
                response = client.post(
                    f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
                )

        with then("it returns 200 with status ERROR and no k8s resources are created"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.ERROR.value))
            k8s.create_deployment.assert_not_called()


# --- skill assignment on agent creation ---


def test_create_agent_with_valid_skill_assigns_it():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.skill.id)]}

        with when("I create an agent with a valid skill"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201, the skill is persisted and present in the response"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(1))
            assert_that(agent_skills[0].skill_id, equal_to(context.skill.id))
            assert_that(len(body["skills"]), equal_to(1))
            assert_that(body["skills"][0]["id"], equal_to(str(context.skill.id)))
            assert_that(body["skills"][0]["name"], equal_to("My Skill"))


def test_create_agent_with_skill_from_other_org_returns_404():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.other_org_skill.id)]}

        with when("I create an agent using a skill that belongs to another org"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_with_unknown_skill_id_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        from uuid import uuid4

        payload = {**_VALID_CREATE, "skill_ids": [str(uuid4())]}

        with when("I create an agent with a non-existent skill"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_skill_missing_provider_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.skill.id)]}

        with when("I create an agent without providing the required GitHub secret"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 400 naming the skill and the missing provider"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("GitHub Skill"))
            assert_that(response.json()["detail"], contains_string("github"))


def test_create_agent_skill_with_covered_provider_assigns_skill():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE,
            "skill_ids": [str(context.skill.id)],
            "secrets": [
                {
                    "provider": "github",
                    "content": {
                        "token": "ghp_token",
                        "owner": "my-org",
                        "repo": "my-repo",
                        "org": "my-org",
                    },
                }
            ],
        }

        with when("I create an agent with the required GitHub secret"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(response.json()["id"]))
            assert_that(len(agent_skills), equal_to(1))


def test_create_agent_duplicate_skill_ids_assigns_skill_once():
    with given([*_GIVEN, there_is_a_skill(name="Dedup Skill")]) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)
        payload = {**_VALID_CREATE, "skill_ids": [skill_id, skill_id]}

        with when("I create an agent with the same skill_id twice"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is assigned only once"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(response.json()["id"]))
            assert_that(len(agent_skills), equal_to(1))


# --- skill assignment on agent update ---


def test_patch_agent_adds_skill():
    with given(
        [*_GIVEN, there_is_an_agent(), there_is_a_skill(name="New Skill")]
    ) as context:
        client: TestClient = context.client

        with when("I add a skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(1))
            assert_that(agent_skills[0].skill_id, equal_to(context.skill.id))
            assert_that(len(body["skills"]), equal_to(1))
            assert_that(body["skills"][0]["id"], equal_to(str(context.skill.id)))


def test_patch_agent_removes_skill():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Removable Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I remove the skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is no longer assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(0))
            assert_that(len(body["skills"]), equal_to(0))


def test_patch_agent_add_skill_from_other_org_returns_404():
    with given(
        [*_GIVEN, there_is_an_agent(), there_is_a_skill_for_another_org()]
    ) as context:
        client: TestClient = context.client

        with when("I add a skill from another org via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.other_org_skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_add_unknown_skill_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        from uuid import uuid4

        with when("I add a non-existent skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(uuid4())]},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_add_skill_missing_provider_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I add a skill that requires GitHub without providing the secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 400 naming the skill and the missing provider"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("GitHub Skill"))
            assert_that(response.json()["detail"], contains_string("github"))


# --- skills.json in ConfigMap on start ---


def test_start_agent_with_skill_includes_skills_json_in_configmap():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Mounted Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start an agent that has an assigned skill"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap contains skills.json with the skill's files"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("skills.json"))
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            assert_that(entries[0]["path"], equal_to("skill.md"))


def test_start_agent_without_skills_has_no_skills_json_in_configmap():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start an agent with no assigned skills"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap does not contain skills.json"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, is_not(has_key("skills.json")))


def test_start_agent_with_skill_pointer_injects_pointer_into_tools_md():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Pointed Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the ConfigMap TOOLS.md contains the auto-generated skill pointer"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(
                config_map.data["TOOLS.md"],
                contains_string(
                    'You can use "Pointed Skill" skill in the ./skills folder'
                ),
            )


# --- aai-cli skills auto-attach from configured providers ---

_JIRA_POINTER = "\nFor Jira, use the aai-cli tool. See ./skills/aai-cli/jira_skill.md\n"


def test_start_agent_auto_attaches_aai_cli_skill_for_configured_provider():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="Jira",
                required_providers=[SecretProvider.JIRA],
                global_skill=True,
                tools_pointer=_JIRA_POINTER,
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when(
            "a jira secret is configured but the skill is not explicitly assigned"
        ):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the aai-cli Jira skill is mounted and its pointer injected"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("skills.json"))
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            assert_that(entries[0]["path"], equal_to("skill.md"))
            assert_that(config_map.data["TOOLS.md"], contains_string(_JIRA_POINTER))


def test_start_agent_does_not_auto_attach_skill_for_unconfigured_provider():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="GitHub",
                required_providers=[SecretProvider.GITHUB],
                global_skill=True,
                tools_pointer="\nFor GitHub, use the aai-cli tool.\n",
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("a jira secret is configured but no github secret"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the GitHub skill is not mounted (its provider is not configured)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, is_not(has_key("skills.json")))
            assert_that(
                config_map.data["TOOLS.md"],
                is_not(contains_string("For GitHub, use the aai-cli tool")),
            )


def test_start_agent_auto_attach_does_not_duplicate_explicitly_assigned_skill():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="Jira",
                required_providers=[SecretProvider.JIRA],
                global_skill=True,
                tools_pointer=_JIRA_POINTER,
            ),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("the jira skill is both explicitly assigned and provider-configured"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the skill is mounted exactly once and the pointer appears once"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            assert_that(config_map.data["TOOLS.md"].count(_JIRA_POINTER), equal_to(1))


def test_start_agent_injects_profile_mapping_into_agents_md_openclaw():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("a jira secret is configured and the OpenClaw agent starts"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("AGENTS.md carries the --profile mapping and no-fallback policy"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("--profile jira-work"))
            assert_that(agents_md, contains_string("./skills/aai-cli/"))


def test_start_agent_injects_profile_mapping_into_agents_md_hermes():
    with given(
        [*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]
    ) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("a jira secret is configured and the Hermes agent starts"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("AGENTS.md carries the --profile mapping and no-fallback policy"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("--profile jira-work"))
            assert_that(agents_md, contains_string("./skills/aai-cli/"))


def test_start_agent_no_integrations_leaves_agents_md_unmodified():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("the agent starts with no configured secrets"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("AGENTS.md has no integrations block appended"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(
                config_map.data["AGENTS.md"],
                is_not(contains_string("--profile")),
            )


# --- template required skills ---


def test_create_agent_with_required_skill_marks_it_required():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)
        payload = {**_VALID_CREATE, "skill_ids": [skill_id]}

        with when("I create an agent including the required skill in skill_ids"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            skills = response.json()["skills"]
            assert_that(len(skills), equal_to(1))
            assert_that(skills[0]["id"], equal_to(skill_id))
            assert_that(skills[0]["required"], equal_to(True))


def test_create_agent_missing_required_skill_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent without including the required skill"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_agent_cannot_remove_required_skill_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent with the required skill"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [skill_id]},
                headers=_auth(context),
            ).json()

        with when("I try to remove the required skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"removed_skill_ids": [skill_id]},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_update_agent_repin_missing_required_skill_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="with-skill", name="With Skill"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_slug": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin to a template that requires a skill I haven't provided"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"template_slug": "with-skill", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_agent_repin_with_required_skill_marks_it_required():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="with-skill", name="With Skill"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_slug": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin providing the required skill in skill_ids"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={
                    "template_slug": "with-skill",
                    "template_version": 1,
                    "skill_ids": [skill_id],
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            skills = response.json()["skills"]
            jira = next(s for s in skills if s["id"] == skill_id)
            assert_that(jira["required"], equal_to(True))


def test_list_agents_marks_required_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent with the required skill"):
            client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [skill_id]},
                headers=_auth(context),
            )

        with when("I list agents"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the skill appears with required=true in the list response"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            agents = response.json()["items"]
            assert_that(len(agents), equal_to(1))
            jira = next(s for s in agents[0]["skills"] if s["id"] == skill_id)
            assert_that(jira["required"], equal_to(True))
