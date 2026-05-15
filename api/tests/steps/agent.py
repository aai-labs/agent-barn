import datetime
from typing import cast
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
from api.domains.agents.models import Agent, AgentStatus, AgentTemplate
from api.domains.agents.repository import AgentRepository
from api.domains.auth.utils import set_default_org_id
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import LambdaWith

TEST_ENCRYPTION_KEY: str = Fernet.generate_key().decode()
TEST_SLACK_BOT_TOKEN = "xoxb-test-bot-token"
TEST_SLACK_APP_TOKEN = "xapp-1-test-app-token"
FAKE_LITELLM_KEY = "sk-fake-litellm-key-for-tests"


class MockK8sModule(Module):
    @provider
    @singleton
    def provide_k8s(self) -> KubernetesClient:
        return cast(KubernetesClient, MagicMock(spec=KubernetesClient))


class MockLiteLLMModule(Module):
    @provider
    @singleton
    def provide_litellm(self) -> LiteLLMClient:
        mock = cast(LiteLLMClient, MagicMock(spec=LiteLLMClient))
        mock.generate_key.return_value = FAKE_LITELLM_KEY
        mock.delete_key.return_value = None
        return mock


def there_is_an_agent(
    name: str = "Test Agent",
    status: AgentStatus = AgentStatus.STOPPED,
    deleted: bool = False,
    organization_id: UUID | None = None,
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
            slack_bot_token_encrypted=encrypt_token(
                TEST_SLACK_BOT_TOKEN, TEST_ENCRYPTION_KEY
            ),
            slack_app_token_encrypted=encrypt_token(
                TEST_SLACK_APP_TOKEN, TEST_ENCRYPTION_KEY
            ),
            litellm_key_encrypted=encrypt_token(FAKE_LITELLM_KEY, TEST_ENCRYPTION_KEY),
            status=status,
            template_id=template.id,
            template_version=template.version,
        )

        if deleted:
            agent.deleted_at = datetime.datetime.now(datetime.timezone.utc)

        repository.save(agent)
        context.agent = agent

    return step


def use_org_for_auth():
    def step(context):
        org_id = context.organization.id
        set_default_org_id(org_id)
        return LambdaWith(lambda: None, lambda: set_default_org_id(None))

    return step
