import datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from cryptography.fernet import Fernet
from injector import Module, provider, singleton

from api.domains.agents.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
    DEFAULT_TOOLS_MD,
    DEFAULT_USER_MD,
)
from api.domains.agents.models import (
    Agent,
    AgentPlatform,
    AgentSlackConfig,
    AgentStatus,
    AgentTeamsConfig,
    AgentTemplate,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.utils import set_default_org_id
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import LambdaWith

TEST_ENCRYPTION_KEY: str = Fernet.generate_key().decode()
TEST_SLACK_BOT_TOKEN = "xoxb-test-bot-token"
TEST_SLACK_APP_TOKEN = "xapp-1-test-app-token"
TEST_TEAMS_APP_ID = "test-teams-app-id"
TEST_TEAMS_APP_PASSWORD = "test-teams-app-password"
TEST_TEAMS_TENANT_ID = "test-tenant-id"
FAKE_LITELLM_KEY = "sk-fake-litellm-key-for-tests"


class MockK8sModule(Module):
    @provider
    @singleton
    def provide_k8s(self) -> KubernetesClient:
        mock: Any = MagicMock(spec=KubernetesClient)
        return mock


class MockLiteLLMModule(Module):
    @provider
    @singleton
    def provide_litellm(self) -> LiteLLMClient:
        mock: Any = MagicMock(spec=LiteLLMClient)
        mock.generate_key.return_value = FAKE_LITELLM_KEY
        mock.delete_key.return_value = None
        return mock


def there_is_an_agent(
    name: str = "Test Agent",
    status: AgentStatus = AgentStatus.STOPPED,
    deleted: bool = False,
    organization_id: UUID | None = None,
    model: str = "",
    platform: AgentPlatform = AgentPlatform.SLACK,
):
    def step(context):
        org_id = organization_id or context.organization.id
        repository: AgentRepository = context.injector.get(AgentRepository)

        template = AgentTemplate(
            organization_id=org_id,
            version=1,
            soul_md="# Soul\n\nTest soul.",
            identity_md="# Identity\n\nTest identity.",
            user_md=DEFAULT_USER_MD,
            tools_md=DEFAULT_TOOLS_MD,
            agents_md=DEFAULT_AGENTS_MD,
            boot_md=DEFAULT_BOOT_MD,
            bootstrap_md=DEFAULT_BOOTSTRAP_MD,
            heartbeat_md=DEFAULT_HEARTBEAT_MD,
        )
        repository.save_template(template)

        agent = Agent(
            organization_id=org_id,
            name=name,
            litellm_key_encrypted=encrypt_token(FAKE_LITELLM_KEY, TEST_ENCRYPTION_KEY),
            model=model,
            status=status,
            platform=platform,
            template_id=template.id,
            template_version=template.version,
        )

        if deleted:
            agent.deleted_at = datetime.datetime.now(datetime.timezone.utc)

        repository.save(agent)

        if platform == AgentPlatform.SLACK:
            slack_config = AgentSlackConfig(
                agent_id=agent.id,
                bot_token_encrypted=encrypt_token(
                    TEST_SLACK_BOT_TOKEN, TEST_ENCRYPTION_KEY
                ),
                app_token_encrypted=encrypt_token(
                    TEST_SLACK_APP_TOKEN, TEST_ENCRYPTION_KEY
                ),
            )
            repository.save_slack_config(slack_config)
        elif platform == AgentPlatform.TEAMS:
            teams_config = AgentTeamsConfig(
                agent_id=agent.id,
                app_id_encrypted=encrypt_token(TEST_TEAMS_APP_ID, TEST_ENCRYPTION_KEY),
                app_password_encrypted=encrypt_token(
                    TEST_TEAMS_APP_PASSWORD, TEST_ENCRYPTION_KEY
                ),
                tenant_id=TEST_TEAMS_TENANT_ID,
            )
            repository.save_teams_config(teams_config)

        template.agent_id = agent.id
        repository.save_template(template)

        context.agent = agent

    return step


def use_org_for_auth():
    def step(context):
        org_id = context.organization.id
        set_default_org_id(org_id)
        return LambdaWith(lambda: None, lambda: set_default_org_id(None))

    return step
