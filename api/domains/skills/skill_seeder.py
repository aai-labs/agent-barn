import logging

from api.domains.agents.aai_cli_skills import (
    AAI_CLI_PROVIDER_SKILLS,
    root_relative_files,
)
from api.domains.skills.models import Skill, SkillSource
from api.domains.skills.repository import SkillRepository
from api.domains.templates.slug import slugify

logger = logging.getLogger(__name__)


def _bootstrap_pointer(skill_def: dict, slug: str) -> str | None:
    pointer = skill_def.get("tools_pointer")
    if pointer is None:
        return None
    entry_path = skill_def.get("entry_path", "SKILL.md")
    return pointer.replace(f"./skills/aai-cli/{entry_path}", f"./skills/{slug}/SKILL.md")


def seed_aai_cli_skills(repository: SkillRepository) -> None:
    """Insert missing Platform Skills on a clean install.

    These bundled Markdown files are bootstrap data only. Once a Platform Skill exists,
    its drafts and published versions are owned by the Platform Skill authoring
    flow; API startup must never overwrite database-managed content or metadata.
    """
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        name = skill_def["name"]
        slug = skill_def.get("slug") or slugify(name) or "skill"
        existing = repository.get_by_slug_global(slug)
        if existing is not None:
            continue

        files = root_relative_files(
            skill_def["files"],
            entry_path=skill_def.get("entry_path"),
            root_dir=slug,
        )
        providers = skill_def["required_providers"]
        skill = Skill(
            organization_id=None,
            agent_id=None,
            name=name,
            slug=slug,
            description=skill_def.get("description"),
            root_dir=slug,
            entry_path="SKILL.md",
            source=SkillSource.AAI_CLI,
            required_providers=providers,
            tools_pointer=_bootstrap_pointer(skill_def, slug),
        )
        repository.save(skill)
        repository.publish_version(
            skill.id,
            files,
            description=skill.description,
            required_providers=providers,
        )
        logger.warning("Seeded Platform Skill: %s (v1)", name)
