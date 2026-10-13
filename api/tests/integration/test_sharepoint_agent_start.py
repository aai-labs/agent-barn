"""Starting an agent with SharePoint: aai-cli gets its own delegated Microsoft profile, the refresh
token arrives as a store secret written only for a new sign-in, and the native Teams channel
receives its separate bot credential."""

from unittest.mock import MagicMock

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, is_not

from api.domains.agents.models import AgentType
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_gateway_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.sharepoint import (
    TEAMS_APP_ID,
    TEAMS_APP_PASSWORD,
    FakeMicrosoftIdentityModule,
    agent_base,
    auth,
    sharepoint_is_signed_in,
    sites_are_granted,
    there_is_a_teams_connection,
)

_FINANCE = "https://contoso.sharepoint.com/sites/finance"


def _given(agent_type: AgentType, sharepoint=None):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "API_EXTERNAL_URL": "https://api.test.com",
                "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
                "SKIP_TEAMS_TOKEN_VALIDATION": "true",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeMicrosoftIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(agent_type=agent_type),
        there_is_a_teams_connection(),
        sharepoint or sharepoint_is_signed_in(),
    ]


@pytest.mark.parametrize(
    ("agent_type", "aai_home", "store_dir"),
    [
        # OpenClaw's home isn't on its volume, so the store moves onto it; Hermes' home is.
        (AgentType.OPENCLAW, "/home/node", "/home/node/.openclaw/aai-cli"),
        (AgentType.HERMES, "/opt/data", "/opt/data/.config/aai-cli"),
    ],
)
def test_start_agent_gives_aai_cli_the_delegated_microsoft_profile(
    agent_type: AgentType, aai_home: str, store_dir: str
) -> None:
    with given(_given(agent_type)) as context:
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = context.client.post(f"{agent_base(context)}/start", headers=auth(context))

        with then("aai-cli gets a microsoft_delegated profile on the Teams app, with no token in the config"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            config_map = k8s.create_config_map.call_args.args[1]
            toml = config_map.data["aai-cli-config.toml"]
            assert_that(toml, contains_string("[profiles.sharepoint-work]"))
            assert_that(toml, contains_string('auth_type = "microsoft_delegated"'))
            assert_that(toml, contains_string(f'client_id = "{TEAMS_APP_ID}"'))
            assert_that(toml, contains_string(f'secrets_file = "{store_dir}/aai-secrets.enc.json"'))
            assert_that(toml, is_not(contains_string("rt-from-exchange")))

        with then("the refresh token reaches the pod as a store secret, written only for a new sign-in"):
            secret = k8s.create_secret.call_args.args[1]
            assert_that(
                secret.string_data["AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN"], equal_to("rt-from-exchange")
            )
            setup = config_map.data["aai-cli-setup.sh"]
            assert_that(setup, contains_string(f"export HOME={aai_home}"))
            assert_that(setup, contains_string("$AAI_SHAREPOINT_SIGN_IN_ID"))
            assert_that(setup, contains_string("secrets set microsoft.sharepoint_refresh_token"))

        with then("native Teams gets its bot credential separately from the delegated SharePoint profile"):
            bot_secret_key = "MSTEAMS_APP_PASSWORD" if agent_type == AgentType.OPENCLAW else "TEAMS_CLIENT_SECRET"
            assert_that(secret.string_data[bot_secret_key], equal_to(TEAMS_APP_PASSWORD))
            assert_that("AAI_SECRET_MICROSOFT_CLIENT_SECRET" in secret.string_data, equal_to(False))
            assert_that("\n".join(config_map.data.values()), is_not(contains_string(TEAMS_APP_PASSWORD)))

        with then("the agent is told it has SharePoint only, through the Microsoft skill"):
            assert_that(config_map.data["AGENTS.md"], contains_string("./skills/aai-microsoft/SKILL.md"))


@pytest.mark.parametrize("agent_type", [AgentType.OPENCLAW, AgentType.HERMES])
def test_start_agent_without_integrations_still_cleans_up_a_removed_sharepoint_sign_in(agent_type: AgentType) -> None:
    with given(_given(agent_type)) as context:
        removed = context.client.patch(
            agent_base(context), json={"removed_secret_providers": ["sharepoint"]}, headers=auth(context)
        )
        assert removed.status_code == status.HTTP_200_OK, removed.text
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent, which now has no aai-cli integrations"):
            response = context.client.post(f"{agent_base(context)}/start", headers=auth(context))

        with then("there's no config, but the boot script still removes the old SharePoint token"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that("aai-cli-config.toml" in config_map.data, equal_to(False))
            setup = config_map.data["aai-cli-setup.sh"]
            assert_that(setup, contains_string("secrets remove microsoft.sharepoint_refresh_token"))
            assert_that(setup, is_not(contains_string("cp /app/config/aai-cli-config.toml")))


@pytest.mark.parametrize(
    ("agent_type", "aai_home"),
    [(AgentType.OPENCLAW, "/home/node"), (AgentType.HERMES, "/opt/data")],
)
def test_start_agent_with_selected_sites_fetches_tokens_from_the_platform(agent_type: AgentType, aai_home: str) -> None:
    with given(_given(agent_type, sharepoint=sites_are_granted(_FINANCE))) as context:
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = context.client.post(f"{agent_base(context)}/start", headers=auth(context))

        with then("aai-cli gets a token_url profile pointing at this agent's token endpoint"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            config_map = k8s.create_config_map.call_args.args[1]
            toml = config_map.data["aai-cli-config.toml"]
            assert_that(toml, contains_string('auth_type = "token_url"'))
            assert_that(
                toml,
                contains_string(
                    f'token_url = "http://agentbarn-api:8001/ingest/v1/agents/{context.agent.id}'
                    '/integrations/sharepoint/token"'
                ),
            )
            assert_that(toml, contains_string('api_token_secret = "agentfarm.ingest_key"'))

        with then("the boot script stores the agent's platform key, and no SharePoint token reaches the pod"):
            setup = config_map.data["aai-cli-setup.sh"]
            assert_that(setup, contains_string(f"export HOME={aai_home}"))
            assert_that(setup, contains_string("secrets set agentfarm.ingest_key"))
            secret = k8s.create_secret.call_args.args[1]
            assert_that("AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN" in secret.string_data, equal_to(False))

        with then("the Teams app's secret reaches the pod only as native Teams' bot credential"):
            bot_secret_key = "MSTEAMS_APP_PASSWORD" if agent_type == AgentType.OPENCLAW else "TEAMS_CLIENT_SECRET"
            others = [value for key, value in secret.string_data.items() if key != bot_secret_key]
            assert_that("\n".join([*config_map.data.values(), *others]), is_not(contains_string(TEAMS_APP_PASSWORD)))

        with then("the agent is told which sites it can reach"):
            assert_that(config_map.data["TOOLS.md"], contains_string(_FINANCE))


@pytest.mark.parametrize("agent_type", [AgentType.HERMES, AgentType.OPENCLAW])
def test_selected_sites_isolation_uses_bound_gateway_and_preserves_app_only_sign_in(agent_type):
    with given([*_given(agent_type, sites_are_granted(_FINANCE)), prepare_gateway_server()]) as context:
        base = agent_base(context)
        response = context.client.put(
            f"{base}/integrations/sharepoint/isolation",
            headers=auth(context),
            json={"isolated": True, "restart": False},
        )
        assert response.status_code == 200, response.text
        response = context.client.post(f"{base}/start", headers=auth(context))
        assert response.status_code == 200, response.text
        k8s = context.injector.get(KubernetesClient)
        environment = k8s.create_secret.call_args.args[1].string_data
        assert "AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN" not in environment
        token = environment["AF_GATEWAY_TOKEN_SHAREPOINT"]
        headers = {"Authorization": f"Bearer {token}"}
        assert context.gateway_client.post("/gateway/v1/token", headers=headers).status_code == 403
        # There is no delegated grant to import, even if an earlier PVC marker exists.
        response = context.gateway_client.post(
            "/gateway/v1/sharepoint/handoff",
            headers=headers,
            json={"store": "obsolete-delegated-store", "key": "obsolete-key", "marker": "earlier-sign-in"},
        )
        assert response.status_code == 204, response.text
        repeat = context.gateway_client.post("/gateway/v1/sharepoint/handoff", headers=headers, json={})
        assert repeat.status_code == 204
        response = context.gateway_client.post("/gateway/v1/token", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["access_token"]
        response = context.client.put(
            f"{base}/integrations/sharepoint/isolation",
            headers=auth(context),
            json={"isolated": False, "restart": True},
        )
        assert response.status_code == 200, response.text
        assert context.gateway_client.post("/gateway/v1/token", headers=headers).status_code == 403
        config = k8s.create_config_map.call_args.args[1].data["aai-cli-config.toml"]
        assert 'api_token_secret = "agentfarm.ingest_key"' in config
        assert "AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN" not in k8s.create_secret.call_args.args[1].string_data


def test_selected_sites_refused_app_token_leaves_handoff_incomplete():
    from api.domains.agents.microsoft_identity import MicrosoftIdentityUnavailable
    from api.domains.integrations.repository import IntegrationRepository
    from api.tests.steps.sharepoint import fake_identity

    with given([*_given(AgentType.HERMES, sites_are_granted(_FINANCE)), prepare_gateway_server()]) as context:
        base = agent_base(context)
        response = context.client.put(
            f"{base}/integrations/sharepoint/isolation",
            headers=auth(context),
            json={"isolated": True, "restart": False},
        )
        assert response.status_code == 200
        response = context.client.post(f"{base}/start", headers=auth(context))
        assert response.status_code == 200
        k8s = context.injector.get(KubernetesClient)
        token = k8s.create_secret.call_args.args[1].string_data["AF_GATEWAY_TOKEN_SHAREPOINT"]
        fake_identity(context).app_token_result = MicrosoftIdentityUnavailable()
        response = context.gateway_client.post(
            "/gateway/v1/sharepoint/handoff",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 502, response.text
        runtime = context.injector.get(IntegrationRepository).runtime(context.agent.id)
        assert runtime.authentication_complete is False
        assert not runtime.bindings["sharepoint"].get("handoff_complete")
