from api.domains.templates.models import PlatformTemplate
from api.domains.templates.predefined import PREDEFINED_TEMPLATES


def build_predefined_templates() -> list[PlatformTemplate]:
    """v1 rows for every pre-defined template, ready to insert as global
    platform resources.

    Predefined templates live in the platform_template table (no
    organization_id), like built-in aai_cli skills, so a single row is shared
    by every organization.
    """
    return [
        PlatformTemplate(
            template_slug=predefined.slug,
            template_name=predefined.name,
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
