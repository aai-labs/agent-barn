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
    slug: str = "test-template",
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
            template_slug=slug,
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


def there_is_a_template_skill():
    """Attach context.skill to context.template as a required skill."""

    def step(context):
        from sqlmodel import Session

        from api.domains.agents.models import AgentTemplateSkill
        from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

        delegate: PostgresRepositoryDelegate = context.injector.get(
            PostgresRepositoryDelegate
        )
        with Session(delegate.engine) as session:
            session.add(
                AgentTemplateSkill(
                    template_id=context.template.id,
                    skill_id=context.skill.id,
                )
            )
            session.commit()
        context.template_skill = (context.template.id, context.skill.id)

    return step
