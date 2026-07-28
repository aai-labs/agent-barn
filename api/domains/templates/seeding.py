from api.domains.templates.models import PlatformTemplate
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


def predefined_content_differs(existing: PlatformTemplate, desired: PlatformTemplate) -> bool:
    """True if any owned content field differs between the two templates."""
    return any(getattr(existing, field) != getattr(desired, field) for field in PREDEFINED_CONTENT_FIELDS)


def copy_predefined_content(existing: PlatformTemplate, desired: PlatformTemplate) -> None:
    """Overwrite ``existing``'s owned content fields with ``desired``'s values."""
    for field in PREDEFINED_CONTENT_FIELDS:
        setattr(existing, field, getattr(desired, field))


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
