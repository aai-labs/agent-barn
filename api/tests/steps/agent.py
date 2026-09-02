import datetime
import uuid as uuid_mod
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from cryptography.fernet import Fernet
from injector import Module, provider, singleton

from api.domains.agents.models import (
    Agent,
    AgentAccess,
    AgentStatus,
    AgentType,
)
from api.domains.agents.repository import AgentRepository
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID
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
from api.domains.templates.slug import generate_template_key
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient

TEST_ENCRYPTION_KEY: str = Fernet.generate_key().decode()
TEST_SLACK_BOT_TOKEN = "xoxb-test-bot-token"
TEST_SLACK_APP_TOKEN = "xapp-1-test-app-token"
TEST_TELEGRAM_BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
TEST_DISCORD_BOT_TOKEN = "test-discord-bot-token"
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
        mock.delete_key.return_value = True
        return mock


def there_is_an_agent(
    name: str = "Test Agent",
    status: AgentStatus = AgentStatus.STOPPED,
    deleted: bool = False,
    organization_id: UUID | None = None,
    model: str = "",
    platform: str | None = None,
    agent_type: AgentType = AgentType.OPENCLAW,
    soul_md: str = "# Soul\n\nTest soul.",
    tools_md: str = DEFAULT_TOOLS_MD,
    bot_token: str | None = None,
    created_by_user_id: UUID | None = None,
    creator_membership_id: UUID | None = None,
):
    def step(context):
        org_id = organization_id or context.organization.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        template_repository: TemplateRepository = context.injector.get(TemplateRepository)

        template = AgentTemplate(
            organization_id=org_id,
            template_key=generate_template_key(),
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
            created_by_user_id=created_by_user_id,
            name=name,
            litellm_key_encrypted=encrypt_token(FAKE_LITELLM_KEY, TEST_ENCRYPTION_KEY),
            model=model,
            status=status,
            agent_type=agent_type,
            agent_template_id=template.id,
        )

        if deleted:
            agent.deleted_at = datetime.datetime.now(datetime.UTC)

        if creator_membership_id is None:
            repository.save(agent)
        else:
            repository.create_with_creator_access(
                agent,
                creator_membership_id,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=created_by_user_id or uuid_mod.uuid4()),
            )

        context.agent = agent

    return step


def there_is_agent_access(
    membership_id: UUID | None = None,
    agent_id: UUID | None = None,
    access_role_id: UUID = AGENT_EDITOR_ROLE_ID,
):
    def step(context):
        repository: AgentRepository = context.injector.get(AgentRepository)
        membership = membership_id or context.organization_user.id
        target_agent = agent_id or context.agent.id
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=membership,
                agent_id=target_agent,
                access_role_id=access_role_id,
            )
        )

    return step


def use_org_for_auth():
    def step(context):
        org_id = context.organization.id
        original_request = context.client.request

        def request(method, url, *args, **kwargs):
            if isinstance(url, str):
                url = url.replace("{organization_id}", str(org_id))
            return original_request(method, url, *args, **kwargs)

        context.client.request = request

        def cleanup():
            context.client.request = original_request

        from api.tests.core.givenpy import LambdaWith

        return LambdaWith(lambda: None, cleanup)

    return step


def there_is_a_shared_credential(
    provider: str = "jira",
    name: str = "Shared Jira",
    content: dict | None = None,
):
    def step(context):
        from api.domains.agents.models import (
            SecretProvider,
            encrypt_content,
            validate_content,
        )
        from api.domains.shared_credentials.models import SharedCredential
        from api.domains.shared_credentials.repository import (
            SharedCredentialRepository,
        )

        default_contents: dict[str, dict] = {
            "jira": {
                "site_url": "https://test.atlassian.net",
                "email": "admin@test.com",
                "api_token": "shared-jira-token",
            },
            "github": {
                "token": "ghp_shared_token",
                "owner": "shared-org",
                "org": "shared-org",
                "repos": [],
            },
        }
        raw = content or default_contents.get(provider, {})
        sp = SecretProvider(provider)
        validated = validate_content(sp, raw)
        encrypted = encrypt_content(validated, TEST_ENCRYPTION_KEY)

        repo: SharedCredentialRepository = context.injector.get(SharedCredentialRepository)
        cred = SharedCredential(
            organization_id=context.organization.id,
            provider=SecretProvider(provider),
            name=name,
            content=encrypted,
            created_by=context.user.id,
        )
        repo.save(cred)
        context.shared_credential = cred

    return step


def skill_is_assigned_to_agent():
    def step(context):
        from api.domains.agents.models import AgentSkill
        from api.domains.agents.repository import AgentRepository
        from api.domains.skills.repository import SkillRepository

        skill_repo: SkillRepository = context.injector.get(SkillRepository)
        latest = skill_repo.get_latest_version(context.skill.id)
        pinned = latest.version if latest else 1
        repo: AgentRepository = context.injector.get(AgentRepository)
        repo.save_skills([AgentSkill(agent_id=context.agent.id, skill_id=context.skill.id, pinned_version=pinned)])

    return step


def there_is_an_agent_in_another_org(
    name: str = "Other Org Agent",
    bot_token: str = TEST_SLACK_BOT_TOKEN,
):
    def step(context):
        from api.tests.steps.organization import there_is_an_organization

        original_org = context.organization
        there_is_an_organization(name="Other Org")(context)
        other_org_id = context.organization.id
        context.organization = original_org

        there_is_an_agent(name=name, bot_token=bot_token, organization_id=other_org_id)(context)
        context.other_org_agent = context.agent

    return step


def there_is_a_skill_for_another_org():
    def step(context):
        from api.tests.steps.organization import there_is_an_organization

        original_org = context.organization
        there_is_an_organization(name="Other Org")(context)
        other_org_id = context.organization.id
        context.organization = original_org

        from api.domains.skills.models import Skill, SkillSource
        from api.domains.skills.repository import SkillRepository

        skill = Skill(
            organization_id=other_org_id,
            name="Other Org Skill",
            slug="other-org-skill",
            root_dir="other-org-skill",
            entry_path="SKILL.md",
            source=SkillSource.CUSTOM,
            required_providers=[],
        )
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(skill)
        repo.publish_version(skill.id, [("SKILL.md", "# Other Org Skill")])
        context.other_org_skill = skill

    return step


def there_is_a_skill(
    name: str = "Test Skill",
    required_providers: list | None = None,
    global_skill: bool = False,
    tools_pointer: str | None = None,
):
    def step(context):
        from api.domains.skills.models import Skill, SkillSource
        from api.domains.skills.repository import SkillRepository
        from api.domains.templates.slug import slugify

        org_id = None if global_skill else context.organization.id
        source = SkillSource.AAI_CLI if global_skill else SkillSource.CUSTOM
        slug = slugify(name)

        skill = Skill(
            organization_id=org_id,
            name=name,
            slug=slug,
            # Every lineage gets an isolated runtime root, including built-ins.
            root_dir=slug,
            entry_path="SKILL.md",
            source=source,
            required_providers=required_providers or [],
            # Custom skills leave this NULL so the pointer is derived from metadata.
            tools_pointer=tools_pointer,
        )
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(skill)
        repo.publish_version(skill.id, [("SKILL.md", f"# {name}")])
        context.skill = skill

    return step
