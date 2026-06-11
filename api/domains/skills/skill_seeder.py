import logging

from api.domains.agents.aai_cli_skills import AAI_CLI_PROVIDER_SKILLS, build_zip
from api.domains.skills.models import Skill, SkillSource
from api.domains.skills.repository import SkillRepository

logger = logging.getLogger(__name__)


def seed_aai_cli_skills(repository: SkillRepository) -> None:
    """Ensure all built-in AAI_CLI skills exist in the DB."""
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        name = skill_def["name"]
        if repository.get_by_name_global(name) is not None:
            continue
        skill = Skill(
            organization_id=None,
            name=name,
            source=SkillSource.AAI_CLI,
            required_providers=skill_def["required_providers"],
            zip_content=build_zip(skill_def["files"]),
        )
        repository.save(skill)
        logger.info("Seeded AAI_CLI skill: %s", name)