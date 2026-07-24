"""Guard: every aai-cli skill path referenced in a predefined template must
correspond to a real seeded skill file.

The templates instruct the agent to "read the skill file first". If a referenced
path is not actually mounted under ./skills, the agent is sent to a file that does
not exist. Each aai-cli provider seeds a single flat file (e.g. aai-cli/jira_skill.md),
mounted at ./skills/aai-cli/jira_skill.md.
"""

import re

from api.domains.agents.aai_cli_skills import AAI_CLI_PROVIDER_SKILLS
from api.domains.templates.predefined import PREDEFINED_TEMPLATES

# Mounted path = ./skills/<skill_file_path>. See init-openclaw.js skill reconstruction.
VALID_SKILL_PATHS = {
    f"./skills/{f['skill_file_path']}" for skill_def in AAI_CLI_PROVIDER_SKILLS for f in skill_def["files"]
}

_PATH_RE = re.compile(r"\./skills/aai-cli/[^\s`)]+\.md")


def _all_template_text(template) -> str:
    return "\n".join(
        getattr(template, field)
        for field in (
            "soul_md",
            "identity_md",
            "user_md",
            "tools_md",
            "agents_md",
            "boot_md",
            "bootstrap_md",
            "heartbeat_md",
        )
    )


def test_predefined_templates_reference_only_real_skill_files():
    for template in PREDEFINED_TEMPLATES:
        referenced = set(_PATH_RE.findall(_all_template_text(template)))
        missing = referenced - VALID_SKILL_PATHS
        assert not missing, (
            f"Template '{template.slug}' references skill paths that are not seeded: "
            f"{sorted(missing)}. Valid paths: {sorted(VALID_SKILL_PATHS)}"
        )
