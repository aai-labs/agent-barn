import logging

from api.domains.agents.aai_cli_skills import (
    AAI_CLI_PROVIDER_SKILLS,
    AAI_CLI_ROOT_DIR,
    root_relative_files,
)
from api.domains.skills.models import Skill, SkillSource
from api.domains.skills.repository import SkillRepository
from api.domains.templates.slug import slugify

logger = logging.getLogger(__name__)


def seed_aai_cli_skills(repository: SkillRepository) -> None:
    """Ensure all built-in AAI_CLI skills exist, publishing a version when content changes.

    Runs on every API startup. Metadata is reconciled in place, but content is
    append-only: a new version is published only when the shipped files differ from
    the latest stored version, so restarting the API does not inflate version
    history or make every agent look out of date.
    """
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        name = skill_def["name"]
        files = root_relative_files(skill_def["files"])
        skill = repository.get_by_name_global(name)

        if skill is None:
            skill = Skill(
                organization_id=None,
                name=name,
                slug=slugify(name),
                root_dir=AAI_CLI_ROOT_DIR,
                entry_path=skill_def["entry_path"],
                source=SkillSource.AAI_CLI,
                required_providers=skill_def["required_providers"],
                tools_pointer=skill_def.get("tools_pointer"),
            )
            repository.save(skill)
            repository.publish_version(skill.id, files)
            logger.warning("Seeded AAI_CLI skill: %s (v1)", name)
            continue

        skill.required_providers = skill_def["required_providers"]
        skill.tools_pointer = skill_def.get("tools_pointer")
        skill.root_dir = AAI_CLI_ROOT_DIR
        skill.entry_path = skill_def["entry_path"]
        repository.save(skill)

        latest = repository.get_latest_version(skill.id)
        stored = {f.path: f.content for f in repository.get_files(latest.id)} if latest else {}
        if stored == dict(files):
            continue
        version = repository.publish_version(skill.id, files)
        logger.warning("Published AAI_CLI skill %s v%d", name, version.version)
