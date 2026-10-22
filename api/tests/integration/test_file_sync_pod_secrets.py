from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_items

from api.domains.agents.microsoft_identity import MicrosoftAppTokens, MicrosoftIdentityClient, MicrosoftTokens
from api.domains.agents.models import AgentType
from api.domains.sync_provider.plugins.onedrive import ONEDRIVE_PROVIDER_KEY
from api.domains.sync_provider.repository import SyncProviderRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given
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

_TENANT_ID = "11111111-2222-4333-8444-555555555555"
_CLIENT_ID = "onedrive-sync-client-id-marker"
_CLIENT_SECRET = "onedrive-sync-client-secret-marker"
_APP_TOKEN = "onedrive-app-token-marker"


def _given(agent_type: AgentType):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "ONEDRIVE_SYNC_CLIENT_ID": _CLIENT_ID,
                "ONEDRIVE_SYNC_CLIENT_SECRET": _CLIENT_SECRET,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        prepare_gateway_server(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(agent_type=agent_type),
        _there_is_an_active_onedrive_connection,
        _the_platform_holds_an_app_token,
    ]


def _there_is_an_active_onedrive_connection(context) -> None:
    repository = context.injector.get(SyncProviderRepository)
    pending = repository.create_pending(
        context.organization.id,
        ONEDRIVE_PROVIDER_KEY,
        schema_version=1,
        account_id=_TENANT_ID,
        connected_by_user_id=context.user.id,
        credentials_encrypted="encrypted-token",
        pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    connection = repository.activate(
        pending.id,
        location_id="site-id",
        location_name="Site",
        location_url="https://contoso.sharepoint.com/sites/site",
        folder_id="agent-barn-folder-id",
        folder_web_url="https://contoso.sharepoint.com/sites/site/Agent%20Barn",
        provider_data={"permission_id": "permission-id"},
    )
    assert connection is not None


def _the_platform_holds_an_app_token(context) -> None:
    issued = MicrosoftTokens(access_token=_APP_TOKEN, refresh_token=None, expires_in=3600, scope="", id_token=None)
    with patch.object(MicrosoftIdentityClient, "client_credentials", return_value=issued):
        token = context.injector.get(MicrosoftAppTokens).get(
            tenant_id=_TENANT_ID, client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET
        )
    assert token == _APP_TOKEN


@pytest.mark.parametrize("agent_type", [AgentType.OPENCLAW, AgentType.HERMES])
def test_starting_an_agent_never_gives_its_pod_the_providers_credentials(agent_type):
    with given(_given(agent_type)) as context:
        cluster = context.injector.get(KubernetesClient)
        cluster.reset_mock()

        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/start",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        config_map = cluster.create_config_map.call_args.args[1]
        assert_that(list(config_map.data), has_items("file-sync.py", "file-sync-rules.json"))
        sent = str(cluster.mock_calls)
        for credential in (_APP_TOKEN, _CLIENT_SECRET):
            assert_that(credential in sent, equal_to(False), credential)
