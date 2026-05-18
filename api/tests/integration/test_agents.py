from fastapi import status
from hamcrest import assert_that, equal_to, has_key, is_not, none
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/agents"

_VALID_CREATE = {
    "name": "My Agent",
    "slack_bot_token": "xoxb-real-bot-token",
    "slack_app_token": "xapp-1-real-app-token",
    "soul_md": "# Soul\n\nThe agent's soul.",
    "identity_md": "# Identity\n\nThe agent's identity.",
}

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def test_create_agent_returns_201():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent with valid data"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 with the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("My Agent"))
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(body, is_not(has_key("slack_bot_token")))
            assert_that(body, is_not(has_key("slack_app_token")))


def test_create_agent_missing_soul_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE}
        del payload["soul_md"]

        with when("I create an agent without soul_md"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_agent_missing_identity_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE}
        del payload["identity_md"]

        with when("I create an agent without identity_md"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_agent_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without a token"):
            response = client.post(_BASE, json=_VALID_CREATE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_agent_optional_md_gets_defaults():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent with only mandatory fields"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 and the agent has template_version 1"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["template_version"], equal_to(1))

            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            template = repository.get_template(UUID(body["template_id"]))
            assert_that(template, is_not(none()))
            assert_that(template.user_md, is_not(none()))
            assert_that(template.tools_md, is_not(none()))


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


def test_patch_agent_updates_md_bumps_version():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch an md field"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"soul_md": "# Soul\n\nUpdated soul."},
                headers=_auth(context),
            )

        with then("it returns 200 and template_version is incremented"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["template_version"], equal_to(2))


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
            litellm.generate_key.assert_called_once()


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
            from api.infrastructure.shared.models import Pagination

            agents = repository.find_all_active(
                context.organization.id, AgentFilter(), Pagination(page=1, size=10)
            )
            assert_that(agents.total, equal_to(0))


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


def test_delete_agent_calls_litellm_delete_key():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)

        with when("I delete the agent"):
            response = client.delete(
                f"{_BASE}/{context.agent.id}", headers=_auth(context)
            )

        with then("LiteLLM delete_key was called once"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)


def test_delete_agent_litellm_failure_still_returns_204():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        litellm.delete_key.side_effect = Exception("timeout")

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


def test_start_agent_deployment_runs_init_script():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/start", headers=_auth(context)
            )

        with then("the Deployment command runs the init script"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            deployment = k8s.create_deployment.call_args.args[1]
            command = deployment.spec.template.spec.containers[0].command
            assert_that(command[0], equal_to("sh"))
            assert "node /app/config/init-openclaw.js" in command[2]


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


def test_pair_agent_returns_output():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-xxx-pod"
        k8s.exec_command.return_value = "Pairing approved"

        with when("I pair a running agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 200 with the command output"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["message"], equal_to("Pairing approved"))
            k8s.get_pod_name_for_deployment.assert_called_once()
            k8s.exec_command.assert_called_once()


def test_pair_stopped_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I pair a stopped agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_pair_agent_no_pod_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = None

        with when("I pair a running agent with no pod"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/pair",
                json={"platform": "slack", "code": "abc123"},
                headers=_auth(context),
            )

        with then("it returns 409 and exec was not called"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            k8s.exec_command.assert_not_called()


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
