"""aai-cli skill docs (predefined, source=aai_cli).

One Skill row per provider is seeded into the DB on API startup (organization_id=None,
global). Each provider's .md files are bundled into a single zip stored as zip_content.

Public interface used by the seeder in api/domains/skills/skill_seeder.py.
"""

import io
import json
import zipfile

from api.domains.agents.models import SecretProvider

from .bitbucket import BITBUCKET_SKILLS
from .confluence import CONFLUENCE_SKILLS
from .github import GITHUB_SKILLS
from .gmail import GMAIL_SKILLS
from .jira import JIRA_SKILLS
from .zoho_mail import ZOHO_MAIL_SKILLS

# One entry per aai-cli provider skill seeded into the DB on startup.
AAI_CLI_PROVIDER_SKILLS: list[dict] = [
    {
        "name": "Jira",
        "required_providers": [SecretProvider.JIRA],
        "files": JIRA_SKILLS,
        "tools_pointer": "\nFor Jira, use the aai-cli tool. See ./skills/aai-cli/jira_skill.md\n",
    },
    {
        "name": "Confluence",
        "required_providers": [SecretProvider.CONFLUENCE],
        "files": CONFLUENCE_SKILLS,
        "tools_pointer": "\nFor Confluence, use the aai-cli tool. See ./skills/aai-cli/confluence_skill.md\n",
    },
    {
        "name": "GitHub",
        "required_providers": [SecretProvider.GITHUB],
        "files": GITHUB_SKILLS,
        "tools_pointer": "\nFor GitHub, use the aai-cli tool. See ./skills/aai-cli/github_skill.md\n",
    },
    {
        "name": "Bitbucket",
        "required_providers": [SecretProvider.BITBUCKET],
        "files": BITBUCKET_SKILLS,
        "tools_pointer": "\nFor Bitbucket, use the aai-cli tool. See ./skills/aai-cli/bitbucket_skill.md\n",
    },
    {
        "name": "Gmail",
        "required_providers": [SecretProvider.GMAIL],
        "files": GMAIL_SKILLS,
        "tools_pointer": "\nFor Gmail, use the aai-cli tool. See ./skills/aai-cli/gmail_skill.md\n",
    },
    {
        "name": "Zoho Mail",
        "required_providers": [SecretProvider.ZOHO_MAIL],
        "files": ZOHO_MAIL_SKILLS,
        "tools_pointer": "\nFor Zoho Mail, use the aai-cli tool. See ./skills/aai-cli/zoho_mail_skill.md\n",
    },
]


def build_zip(files: list[dict]) -> bytes:
    """Build an in-memory zip from a list of {skill_file_path, skill_content} dicts."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["skill_file_path"], f["skill_content"])
    return buf.getvalue()


def build_skills_manifest_from_zips(skills: list) -> str:
    """Extract all mounted skill zips and build the ConfigMap manifest.

    skills: list of Skill objects (each exposing ``zip_content``).
    Returns a sorted JSON string of {path, content} entries for all mounted files.
    """
    entries = []
    for skill in skills:
        buf = io.BytesIO(skill.zip_content)
        with zipfile.ZipFile(buf, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/") or name.startswith(("__MACOSX/", "._")):
                    continue
                entries.append({"path": name, "content": zf.read(name).decode()})
    return json.dumps(sorted(entries, key=lambda d: d["path"]))
