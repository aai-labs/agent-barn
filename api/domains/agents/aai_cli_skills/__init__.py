"""aai-cli skill docs (predefined, source=aai_cli).

One Skill row per provider is seeded into the DB on API startup (organization_id=None,
global), each publishing its .md files as a skill version.

All ten built-ins deliberately share the ``aai-cli`` mount directory: their published
pointers ("See ./skills/aai-cli/jira_skill.md") and cross-references inside the markdown
bodies depend on that path, so the directory is not derived from the skill slug the way
it is for custom skills.

Public interface used by the seeder in api/domains/skills/skill_seeder.py.
"""

import json

from api.domains.agents.models import SecretProvider

from .bitbucket import BITBUCKET_SKILLS
from .confluence import CONFLUENCE_SKILLS
from .excel import EXCEL_SKILLS
from .github import GITHUB_SKILLS
from .jira import JIRA_SKILLS
from .pipedrive import PIPEDRIVE_SKILLS
from .slack import SLACK_SKILLS
from .zoho_mail import ZOHO_MAIL_SKILLS

AAI_CLI_ROOT_DIR = "aai-cli"

# One entry per aai-cli skill seeded into the DB on startup. Most are provider-gated, but
# a skill needing no credential (Excel works on local files) carries an empty
# ``required_providers``: it stays selectable, and _auto_mount_skills deliberately skips it
# so it is only ever mounted when someone actually picks it.
AAI_CLI_PROVIDER_SKILLS: list[dict] = [
    {
        "name": "Jira",
        "required_providers": [SecretProvider.JIRA],
        "files": JIRA_SKILLS,
        "entry_path": JIRA_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Jira, use the aai-cli tool. See ./skills/aai-cli/jira_skill.md\n",
    },
    {
        "name": "Confluence",
        "required_providers": [SecretProvider.CONFLUENCE],
        "files": CONFLUENCE_SKILLS,
        "entry_path": CONFLUENCE_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Confluence, use the aai-cli tool. See ./skills/aai-cli/confluence_skill.md\n",
    },
    {
        "name": "GitHub",
        "required_providers": [SecretProvider.GITHUB],
        "files": GITHUB_SKILLS,
        "entry_path": GITHUB_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor GitHub, use the aai-cli tool. See ./skills/aai-cli/github_skill.md\n",
    },
    {
        "name": "Bitbucket",
        "required_providers": [SecretProvider.BITBUCKET],
        "files": BITBUCKET_SKILLS,
        "entry_path": BITBUCKET_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Bitbucket, use the aai-cli tool. See ./skills/aai-cli/bitbucket_skill.md\n",
    },
    {
        "name": "Excel",
        "required_providers": [],
        "files": EXCEL_SKILLS,
        "entry_path": EXCEL_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": (
            "\nFor spreadsheets (.xlsx/.xlsm/.csv/.tsv), use `aai-cli excel` — never Python or "
            "openpyxl. See ./skills/aai-cli/excel_skill.md\n"
        ),
    },
    {
        "name": "Zoho Mail",
        "required_providers": [SecretProvider.ZOHO_MAIL],
        "files": ZOHO_MAIL_SKILLS,
        "entry_path": ZOHO_MAIL_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Zoho Mail, use the aai-cli tool. See ./skills/aai-cli/zoho_mail_skill.md\n",
    },
    {
        "name": "Slack",
        "required_providers": [SecretProvider.SLACK],
        "files": SLACK_SKILLS,
        "entry_path": SLACK_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Slack, use the aai-cli tool. See ./skills/aai-cli/slack_skill.md\n",
    },
    {
        "name": "Pipedrive",
        "required_providers": [SecretProvider.PIPEDRIVE],
        "files": PIPEDRIVE_SKILLS,
        "entry_path": PIPEDRIVE_SKILLS[0]["skill_file_path"].removeprefix(AAI_CLI_ROOT_DIR + "/"),
        "tools_pointer": "\nFor Pipedrive, use the aai-cli tool. See ./skills/aai-cli/pipedrive_skill.md\n",
    },
]


def root_relative_files(files: list[dict]) -> list[tuple[str, str]]:
    """Strip the shared aai-cli/ prefix from a built-in's declared file paths.

    Paths are stored relative to the skill root and re-prefixed with ``root_dir`` at
    mount time, so the on-disk result is unchanged.
    """
    prefix = f"{AAI_CLI_ROOT_DIR}/"
    return [
        (
            f["skill_file_path"].removeprefix(prefix),
            f["skill_content"],
        )
        for f in files
    ]


def build_skills_manifest(skills: list, files_by_skill_id: dict) -> tuple[str, list[str]]:
    """Build the ConfigMap manifest for a set of mounted skills.

    Returns the sorted JSON string of {path, content} entries plus a list of
    human-readable collision descriptions. Two skills can legitimately share a
    ``root_dir`` (all built-ins share ``aai-cli``), so a file path can be claimed
    twice; skills are applied in a stable order and the first claim wins, with the
    losers reported so the caller can log them against the agent.
    """
    entries: list[dict[str, str]] = []
    claimed_by: dict[str, str] = {}
    collisions: list[str] = []

    for skill in sorted(skills, key=lambda s: (s.name, str(s.id))):
        for file in files_by_skill_id.get(skill.id, []):
            path = f"{skill.root_dir}/{file.path}"
            owner = claimed_by.get(path)
            if owner is not None:
                collisions.append(f"{path!r} claimed by both {owner!r} and {skill.name!r}")
                continue
            claimed_by[path] = skill.name
            entries.append({"path": path, "content": file.content})

    return json.dumps(sorted(entries, key=lambda d: d["path"])), collisions
