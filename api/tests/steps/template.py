from uuid import UUID

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
from api.domains.templates.models import AgentTemplate, TemplateSource
from api.domains.templates.repository import TemplateRepository


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
                version = SkillVersion(skill_id=skill.id, version=1)
                session.add(version)
                session.flush()
                session.add(SkillFile(skill_version_id=version.id, path="SKILL.md", content=f"# {name}"))
                session.add(
                    AgentTemplateSkill(
                        template_id=context.template.id,
                        skill_id=skill.id,
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
