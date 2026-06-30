import logging

from api.domains.agents.aai_cli_skills import AAI_CLI_PROVIDER_SKILLS, build_zip
from api.domains.skills.models import Skill, SkillSource
from api.domains.skills.repository import SkillRepository

logger = logging.getLogger(__name__)


def seed_aai_cli_skills(repository: SkillRepository) -> None:
    """Ensure all built-in AAI_CLI skills exist in the DB, updating content when changed."""
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        name = skill_def["name"]
        new_zip = build_zip(skill_def["files"])
        new_pointer = skill_def.get("tools_pointer")
        existing = repository.get_by_name_global(name)
        if existing is not None:
            existing.zip_content = new_zip
            existing.tools_pointer = new_pointer
            repository.save(existing)
            logger.warning("Updated AAI_CLI skill: %s", name)
            continue
        skill = Skill(
            organization_id=None,
            name=name,
            source=SkillSource.AAI_CLI,
            required_providers=skill_def["required_providers"],
            zip_content=new_zip,
            tools_pointer=new_pointer,
        )
        repository.save(skill)
        logger.warning("Seeded AAI_CLI skill: %s", name)
