import datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from cryptography.fernet import Fernet
from injector import Module, provider, singleton

from api.domains.agents.models import (
    Agent,
    AgentPlatform,
    AgentSlackConfig,
    AgentStatus,
    AgentTeamsConfig,
    AgentType,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.utils import set_default_org_id
from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
    DEFAULT_TOOLS_MD,
    DEFAULT_USER_MD,
)
from api.domains.templates.models import AgentTemplate, TemplateSource
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.slug import generate_template_slug
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
    agent_type: AgentType = AgentType.OPENCLAW,
    soul_md: str = "# Soul\n\nTest soul.",
    tools_md: str = DEFAULT_TOOLS_MD,
):
    def step(context):
        org_id = organization_id or context.organization.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        template_repository: TemplateRepository = context.injector.get(
            TemplateRepository
        )

        template = AgentTemplate(
            organization_id=org_id,
            template_slug=generate_template_slug(name),
            template_name=name,
            template_source=TemplateSource.CUSTOM,
            version=1,
            soul_md=soul_md,
            identity_md="# Identity\n\nTest identity.",
            user_md=DEFAULT_USER_MD,
            tools_md=tools_md,
            agents_md=DEFAULT_AGENTS_MD,
            boot_md=DEFAULT_BOOT_MD,
            bootstrap_md=DEFAULT_BOOTSTRAP_MD,
            heartbeat_md=DEFAULT_HEARTBEAT_MD,
        )
        template_repository.save_template(template)

        agent = Agent(
            organization_id=org_id,
            name=name,
            litellm_key_encrypted=encrypt_token(FAKE_LITELLM_KEY, TEST_ENCRYPTION_KEY),
            model=model,
            status=status,
            platform=platform,
            agent_type=agent_type,
            template_slug=template.template_slug,
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

        context.agent = agent

    return step


def use_org_for_auth():
    def step(context):
        org_id = context.organization.id
        set_default_org_id(org_id)
        return LambdaWith(lambda: None, lambda: set_default_org_id(None))

    return step


def skill_is_assigned_to_agent():
    def step(context):
        from api.domains.agents.models import AgentSkill
        from api.domains.agents.repository import AgentRepository

        repo: AgentRepository = context.injector.get(AgentRepository)
        repo.save_skills(
            [AgentSkill(agent_id=context.agent.id, skill_id=context.skill.id)]
        )

    return step


def there_is_a_skill_for_another_org():
    def step(context):
        from api.tests.steps.organization import there_is_an_organization

        original_org = context.organization
        there_is_an_organization(name="Other Org")(context)
        other_org_id = context.organization.id
        context.organization = original_org

        import io
        import zipfile

        from api.domains.skills.models import Skill, SkillSource
        from api.domains.skills.repository import SkillRepository

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("skill.md", "# Other Org Skill")

        skill = Skill(
            organization_id=other_org_id,
            name="Other Org Skill",
            source=SkillSource.CUSTOM,
            required_providers=[],
            zip_content=buf.getvalue(),
        )
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(skill)
        context.other_org_skill = skill

    return step


def there_is_a_skill(
    name: str = "Test Skill",
    required_providers: list | None = None,
    global_skill: bool = False,
):
    def step(context):
        import io
        import zipfile

        from api.domains.skills.models import Skill, SkillSource
        from api.domains.skills.repository import SkillRepository

        org_id = None if global_skill else context.organization.id
        source = SkillSource.AAI_CLI if global_skill else SkillSource.CUSTOM
        tools_pointer = (
            None
            if global_skill
            else f'You can use "{name}" skill in the ./skills folder'
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("skill.md", f"# {name}")

        skill = Skill(
            organization_id=org_id,
            name=name,
            source=source,
            required_providers=required_providers or [],
            zip_content=buf.getvalue(),
            tools_pointer=tools_pointer,
        )
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(skill)
        context.skill = skill

    return step
