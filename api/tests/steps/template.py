from uuid import UUID

from sqlmodel import Session

from api.domains.agents.models import AgentTemplateDraftSkill
from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
    DEFAULT_IDENTITY_MD,
    DEFAULT_SOUL_MD,
    DEFAULT_TOOLS_MD,
    DEFAULT_USER_MD,
)
from api.domains.templates.models import AgentTemplate, AgentTemplateDraft, TemplateSource
from api.domains.templates.repository import TemplateRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def there_is_a_template(
    template_key: str = "test-template",
    name: str = "Test Template",
    version: int = 1,
    source: TemplateSource = TemplateSource.CUSTOM,
    organization_id: UUID | None = None,
    soul_md: str = DEFAULT_SOUL_MD,
    identity_md: str = DEFAULT_IDENTITY_MD,
    user_md: str = DEFAULT_USER_MD,
    tools_md: str = DEFAULT_TOOLS_MD,
    agents_md: str = DEFAULT_AGENTS_MD,
    boot_md: str = DEFAULT_BOOT_MD,
    bootstrap_md: str = DEFAULT_BOOTSTRAP_MD,
    heartbeat_md: str = DEFAULT_HEARTBEAT_MD,
):
    def step(context):
        org_id = organization_id or context.organization.id
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = AgentTemplate(
            organization_id=org_id,
            template_key=template_key,
            template_name=name,
            template_source=source,
            version=version,
            soul_md=soul_md,
            identity_md=identity_md,
            user_md=user_md,
            tools_md=tools_md,
            agents_md=agents_md,
            boot_md=boot_md,
            bootstrap_md=bootstrap_md,
            heartbeat_md=heartbeat_md,
        )
        repository.save_template(template)
        context.template = template

    return step


def there_is_an_org_template_draft(
    template_key: str = "test-template",
    name: str = "Test Template",
    source: TemplateSource = TemplateSource.CUSTOM,
    organization_id: UUID | None = None,
    description: str | None = None,
    forked_from_platform_template_id: UUID | None = None,
    fork_baseline_platform_template_id: UUID | None = None,
    fork_baseline_platform_version: int | None = None,
    soul_md: str = DEFAULT_SOUL_MD,
    identity_md: str = DEFAULT_IDENTITY_MD,
    user_md: str = DEFAULT_USER_MD,
    tools_md: str = DEFAULT_TOOLS_MD,
    agents_md: str = DEFAULT_AGENTS_MD,
    boot_md: str = DEFAULT_BOOT_MD,
    bootstrap_md: str = DEFAULT_BOOTSTRAP_MD,
    heartbeat_md: str = DEFAULT_HEARTBEAT_MD,
):
    """Put an unpublished Organization Draft Template Version on the lineage."""

    def step(context):
        org_id = organization_id or context.organization.id
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        draft = AgentTemplateDraft(
            organization_id=org_id,
            template_key=template_key,
            template_name=name,
            template_source=source,
            description=description,
            forked_from_platform_template_id=forked_from_platform_template_id,
            fork_baseline_platform_template_id=fork_baseline_platform_template_id,
            fork_baseline_platform_version=fork_baseline_platform_version,
            soul_md=soul_md,
            identity_md=identity_md,
            user_md=user_md,
            tools_md=tools_md,
            agents_md=agents_md,
            boot_md=boot_md,
            bootstrap_md=bootstrap_md,
            heartbeat_md=heartbeat_md,
        )
        delegate.save(draft)
        context.org_template_draft = draft

    return step


def there_is_an_org_template_draft_skill(group_key: str | None = None, skill_version: int = 1):
    """Require context.skill on context.org_template_draft.

    A None group_key (the default) makes it a standalone AND-required skill."""

    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            session.add(
                AgentTemplateDraftSkill(
                    draft_id=context.org_template_draft.id,
                    skill_id=context.skill.id,
                    skill_version=skill_version,
                    group_key=group_key,
                )
            )
            session.commit()
        context.org_template_draft_skill = (context.org_template_draft.id, context.skill.id)

    return step


def there_is_a_template_skill(group_key: str | None = None):
    """Attach context.skill to context.template as a required skill.

    A None group_key (the default) makes it a standalone AND-required skill,
    matching the original pre-OR-group behavior."""

    def step(context):
        from sqlmodel import Session

        from api.domains.agents.models import AgentTemplateSkill
        from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            session.add(
                AgentTemplateSkill(
                    template_id=context.template.id,
                    skill_id=context.skill.id,
                    skill_version=1,
                    group_key=group_key,
                )
            )
            session.commit()
        context.template_skill = (context.template.id, context.skill.id)

    return step


def there_is_a_template_skill_group(skill_names: tuple[str, ...], group_key: str = "test-group"):
    """Create one org-scoped skill per name and attach all of them to
    context.template as members of the same "at least one of" group."""

    def step(context):
        from sqlmodel import Session

        from api.domains.agents.models import AgentTemplateSkill
        from api.domains.skills.models import Skill, SkillFile, SkillSource, SkillVersion
        from api.domains.templates.slug import slugify
        from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        skills = []
        with Session(delegate.engine) as session:
            for name in skill_names:
                slug = slugify(name)
                skill = Skill(
                    organization_id=context.organization.id,
                    name=name,
                    slug=slug,
                    root_dir=slug,
                    entry_path="SKILL.md",
                    source=SkillSource.CUSTOM,
                    required_providers=[],
                )
                session.add(skill)
                session.flush()
                version = SkillVersion(
                    skill_id=skill.id,
                    version=1,
                    description=None,
                    required_providers=[],
                )
                session.add(version)
                session.flush()
                session.add(SkillFile(skill_version_id=version.id, path="SKILL.md", content=f"# {name}"))
                session.add(
                    AgentTemplateSkill(
                        template_id=context.template.id,
                        skill_id=skill.id,
                        skill_version=1,
                        group_key=group_key,
                    )
                )
                skills.append(skill)
            session.commit()
            for skill in skills:
                session.refresh(skill)
                session.expunge(skill)
        context.template_skill_group = {"group_key": group_key, "skills": skills}

    return step


def agent_uses_template_pin(pin_type: str):
    def step(context):
        from uuid import uuid7

        from api.domains.agents.models import AgentTemplateOverrideSourceType, AgentTemplateOverrideVersion
        from api.domains.templates.models import PlatformTemplate

        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        if not isinstance(template, AgentTemplate):
            raise TypeError("This fixture requires an Organization Template pin")
        snapshot = {
            field: getattr(template, field)
            for field in (
                "template_name",
                "description",
                "soul_md",
                "identity_md",
                "user_md",
                "tools_md",
                "agents_md",
                "boot_md",
                "bootstrap_md",
                "heartbeat_md",
            )
        }
        context.expected_template_pin = (template.template_key, template.version, "shared", None)
        if pin_type == "platform":
            platform = PlatformTemplate(template_key=f"platform-{uuid7()}", version=3, **snapshot)
            context.postgres_delegate.save(platform)
            context.agent.agent_template_id = None
            context.agent.platform_template_id = platform.id
            context.expected_template_pin = (platform.template_key, platform.version, "shared", None)
        elif pin_type == "override":
            override = AgentTemplateOverrideVersion(
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                version=7,
                source_type=AgentTemplateOverrideSourceType.ORGANIZATION,
                source_template_key=template.template_key,
                source_template_version=template.version,
                source_agent_template_id=template.id,
                **snapshot,
            )
            context.postgres_delegate.save(override)
            context.agent.agent_template_id = None
            context.agent.agent_template_override_version_id = override.id
            context.expected_template_pin = (
                override.source_template_key,
                override.version,
                "override",
                override.version,
            )
        elif pin_type != "organization":
            raise ValueError(f"Unknown template pin type: {pin_type}")
        context.postgres_delegate.save(context.agent)

    return step
