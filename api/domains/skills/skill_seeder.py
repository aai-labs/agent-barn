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


def _prune_retired_aai_cli_skills(repository: SkillRepository) -> None:
    """Delete built-in skills that no longer exist in the registry, when nothing uses them.

    Retiring a provider (e.g. the Gmail/Google Sheets aai-cli skills, superseded by the
    gog-backed google_workspace integration) removes its definition from
    ``AAI_CLI_PROVIDER_SKILLS``, but the seeder never deleted rows — so the old skill
    lingered in every database and still auto-mounted for any agent that kept the retired
    credential, handing the agent a doc for a ``--profile`` that is no longer generated.

    Only unreferenced rows are removed: ``agent_skill.skill_id`` cascades, so deleting an
    assigned skill would silently strip it from an agent. Anything still assigned is left
    in place and logged for manual follow-up.
    """
    known = {skill_def["name"] for skill_def in AAI_CLI_PROVIDER_SKILLS}
    for skill in repository.get_aai_cli_skills():
        if skill.name in known:
            continue
        if repository.is_assigned_to_any_agent(skill.id):
            logger.warning(
                "Retired AAI_CLI skill %s is still assigned to an agent; leaving it in place",
                skill.name,
            )
            continue
        repository.delete(skill)
        logger.warning("Pruned retired AAI_CLI skill: %s", skill.name)


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

    _prune_retired_aai_cli_skills(repository)
