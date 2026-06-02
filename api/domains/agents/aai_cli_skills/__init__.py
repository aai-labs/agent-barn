"""aai-cli skill docs (predefined, source=aai_cli).

Package structure: one module per provider, plus _index.py for the top-level index.
Public interface is identical to the old flat aai_cli_skills.py module so all import
sites remain unchanged.
"""

import json
from uuid import UUID

from api.domains.agents.models import AgentSkill, SkillSource

from ._index import AAI_CLI_INDEX_SKILL
from .jira import JIRA_SKILLS
from .confluence import CONFLUENCE_SKILLS
from .github import GITHUB_SKILLS
from .bitbucket import BITBUCKET_SKILLS

# Display label for these rows (UI is out of scope; kept constant for now).
_SKILL_NAME = "aai-cli"

AAI_CLI_SKILLS: list[dict[str, str]] = [
    AAI_CLI_INDEX_SKILL,
    *JIRA_SKILLS,
    *CONFLUENCE_SKILLS,
    *GITHUB_SKILLS,
    *BITBUCKET_SKILLS,
]


def load_aai_cli_skills(agent_id: UUID) -> list[AgentSkill]:
    """Build per-agent AgentSkill rows for the predefined aai-cli skills."""
    return [
        AgentSkill(
            agent_id=agent_id,
            source=SkillSource.AAI_CLI,
            skill_name=entry["skill_name"],
            skill_file_path=entry["skill_file_path"],
            skill_content=entry["skill_content"],
        )
        for entry in AAI_CLI_SKILLS
    ]


def build_skills_manifest(skills: list[AgentSkill]) -> str:
    """Serialize skills to the ConfigMap manifest (path + content only; source is DB-only).

    Source-agnostic: works for any AgentSkill rows, including future custom skills.
    """
    return json.dumps(
        sorted(
            ({"path": s.skill_file_path, "content": s.skill_content} for s in skills),
            key=lambda d: d["path"],
        )
    )
