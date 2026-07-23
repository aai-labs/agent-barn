from uuid import UUID

from api.domains.templates.models import AgentTemplate, TemplateSource
from api.domains.templates.predefined import PREDEFINED_TEMPLATES


# Content fields a predefined template owns; used to detect/propagate code changes.
PREDEFINED_CONTENT_FIELDS: tuple[str, ...] = (
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


def predefined_content_differs(existing: AgentTemplate, desired: AgentTemplate) -> bool:
    """True if any owned content field differs between the two templates."""
    return any(getattr(existing, field) != getattr(desired, field) for field in PREDEFINED_CONTENT_FIELDS)


def copy_predefined_content(existing: AgentTemplate, desired: AgentTemplate) -> None:
    """Overwrite ``existing``'s owned content fields with ``desired``'s values."""
    for field in PREDEFINED_CONTENT_FIELDS:
        setattr(existing, field, getattr(desired, field))


def build_predefined_templates(org_id: UUID) -> list[AgentTemplate]:
    """v1 rows for every pre-defined template, ready to insert for an org."""
    return [
        AgentTemplate(
            organization_id=org_id,
            template_slug=predefined.slug,
            template_name=predefined.name,
            template_source=TemplateSource.PRE_DEFINED,
            version=1,
            description=predefined.description,
            soul_md=predefined.soul_md,
            identity_md=predefined.identity_md,
            user_md=predefined.user_md,
            tools_md=predefined.tools_md,
            agents_md=predefined.agents_md,
            boot_md=predefined.boot_md,
            bootstrap_md=predefined.bootstrap_md,
            heartbeat_md=predefined.heartbeat_md,
        )
        for predefined in PREDEFINED_TEMPLATES
    ]
