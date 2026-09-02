"""Bundled aai-cli skills.

The upstream aai-cli distribution is the source layout for these Platform Skills:
``bundled/skills/aai-<integration>/SKILL.md``.  Each directory contains exactly one
root entry file, and the seeder stores that file as ``SKILL.md`` relative to the
Skill's isolated ``aai-<integration>`` mount directory.

Legacy archive definitions are handled by the migration layer; new installs and the
runtime bootstrap use the bundled Markdown files below instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from api.domains.agents.models import SecretProvider

AAI_CLI_ROOT_DIR = "aai-cli"  # legacy archive root, used only by migration helpers
_BUNDLED_ROOT = Path(__file__).parent / "bundled" / "skills"

# Display names remain friendly in the organization UI while the immutable slug and
# runtime directory match aai-cli's published bundle names.
_DISPLAY_NAMES = {
    "aai-bitbucket": "Bitbucket",
    "aai-confluence": "Confluence",
    "aai-excel": "Excel",
    "aai-github": "GitHub",
    "aai-google-drive": "Google Drive",
    "aai-hubspot": "HubSpot",
    "aai-jira": "Jira",
    "aai-openpanel": "OpenPanel",
    "aai-pipedrive": "Pipedrive",
    "aai-posthog": "PostHog",
    "aai-zoho-mail": "Zoho Mail",
}

_COMMANDS = {
    "aai-bitbucket": "bitbucket",
    "aai-confluence": "confluence",
    "aai-excel": "excel",
    "aai-github": "github",
    "aai-google-drive": "drive",
    "aai-hubspot": "hubspot",
    "aai-jira": "jira",
    "aai-openpanel": "openpanel",
    "aai-pipedrive": "pipedrive",
    "aai-posthog": "posthog",
    "aai-zoho-mail": "email",
}

# These are the integrations whose secret lifecycle is currently implemented by
# Agent Farm. The remaining bundled docs are still available as explicit Platform
# Skills, but are not auto-attached until their credentials are modeled here.
_REQUIRED_PROVIDERS = {
    "aai-bitbucket": [SecretProvider.BITBUCKET],
    "aai-confluence": [SecretProvider.CONFLUENCE],
    "aai-excel": [],
    "aai-github": [SecretProvider.GITHUB],
    "aai-google-drive": [],
    "aai-hubspot": [],
    "aai-jira": [SecretProvider.JIRA],
    "aai-openpanel": [],
    "aai-pipedrive": [SecretProvider.PIPEDRIVE],
    "aai-posthog": [],
    "aai-zoho-mail": [SecretProvider.ZOHO_MAIL],
}


def _frontmatter_value(content: str, key: str) -> str | None:
    in_frontmatter = False
    for line in content.splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def _bundled_skill(directory: str) -> dict:
    skill_dir = _BUNDLED_ROOT / directory
    entry = skill_dir / "SKILL.md"
    content = entry.read_text(encoding="utf-8")
    files = [
        {
            "skill_file_path": f"{directory}/{path.relative_to(skill_dir).as_posix()}",
            "skill_content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file()
    ]
    return {
        "name": _DISPLAY_NAMES[directory],
        "slug": directory,
        "bundle_dir": directory,
        "description": _frontmatter_value(content, "description"),
        "required_providers": _REQUIRED_PROVIDERS[directory],
        "files": files,
        "entry_path": "SKILL.md",
        "tools_pointer": (
            f"\nFor {_DISPLAY_NAMES[directory]}, use the aai-cli tool. See ./skills/{directory}/SKILL.md\n"
        ),
    }


AAI_CLI_PROVIDER_SKILLS: list[dict] = [_bundled_skill(directory) for directory in sorted(_DISPLAY_NAMES)]


def root_relative_files(
    files: list[dict],
    *,
    entry_path: str | None = None,
    root_dir: str | None = None,
) -> list[tuple[str, str]]:
    """Convert bundled or legacy archive paths to files relative to one Skill root.

    The upstream bundle uses ``aai-jira/SKILL.md``. Legacy database archives used
    ``aai-cli/jira_skill.md``. Both forms are accepted here so bootstrap and migration
    tests exercise the same deterministic normalization rule.
    """
    raw_paths = [f["skill_file_path"].replace("\\", "/") for f in files]
    source_roots = {path.split("/", 1)[0] for path in raw_paths if "/" in path}
    source_root = next(iter(source_roots)) if len(source_roots) == 1 else None
    prefix = f"{source_root}/" if source_root else ""
    relative = [(path.removeprefix(prefix), f["skill_content"]) for path, f in zip(raw_paths, files, strict=True)]
    legacy_entry = (entry_path or (relative[0][0] if relative else "")).removeprefix(prefix)
    mount_root = root_dir or source_root or AAI_CLI_ROOT_DIR

    normalized: list[tuple[str, str]] = []
    for path, content in relative:
        new_path = "SKILL.md" if path == legacy_entry else path
        for old_root in (source_root, AAI_CLI_ROOT_DIR):
            if old_root:
                content = content.replace(
                    f"./skills/{old_root}/{legacy_entry}",
                    f"./skills/{mount_root}/SKILL.md",
                )
        normalized.append((new_path, content))
    return normalized


def build_skills_manifest(skills: list, files_by_skill_id: dict) -> tuple[str, list[str]]:
    """Build the deterministic runtime manifest for mounted Skill files.

    A healthy bundle gives every Skill a unique ``aai-<integration>`` root. Collision
    reporting remains as a defense-in-depth check for imported or repaired data.
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
