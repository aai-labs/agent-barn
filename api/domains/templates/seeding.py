from uuid import UUID

from api.domains.templates.models import AgentTemplate, TemplateSource
from api.domains.templates.predefined import PREDEFINED_TEMPLATES


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
