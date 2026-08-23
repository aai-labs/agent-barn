"""Loads predefined (Platform Template) seed content from the `seeds/` directory.

Each template lineage is a subdirectory of `seeds/` (e.g. `seeds/code-reviewer/`)
containing a `settings.yaml` (name, description, required_skills) and up to eight
Markdown artifacts (soul.md, identity.md, user.md, tools.md, agents.md, boot.md,
bootstrap.md, heartbeat.md). The directory name is the stable key for the
predefined lineage. Any artifact a template omits falls back to the shared file
of the same name in `seeds/_defaults/`.

This directory only feeds the one-time bootstrap seeder (see
`docs/adr/2026-08-03-platform-template-file-based-bootstrap.md`) — once a
lineage exists in the database, further versions are authored through the
Draft Template Version admin flow, not these files.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

SEEDS_DIR = Path(__file__).parent / "seeds"
DEFAULTS_DIR = SEEDS_DIR / "_defaults"

_ARTIFACT_FILES: tuple[str, ...] = (
    "soul.md",
    "identity.md",
    "user.md",
    "tools.md",
    "agents.md",
    "boot.md",
    "bootstrap.md",
    "heartbeat.md",
)


@dataclass(frozen=True)
class PredefinedTemplate:
    key: str
    name: str
    description: str
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str
    # An entry is either a bare skill name (standalone, AND-required) or a
    # tuple of names forming an "at least one of" (OR) requirement group,
    # e.g. ("GitHub", "Bitbucket").
    required_skill_names: tuple[str | tuple[str, ...], ...] = ()


def _read_artifact(template_dir: Path, filename: str) -> str:
    template_specific = template_dir / filename
    if template_specific.exists():
        return template_specific.read_text(encoding="utf-8")
    return (DEFAULTS_DIR / filename).read_text(encoding="utf-8")


def _parse_required_skills(entries: list) -> tuple[str | tuple[str, ...], ...]:
    result: list[str | tuple[str, ...]] = []
    for entry in entries:
        if isinstance(entry, str):
            result.append(entry)
        elif isinstance(entry, dict) and "any_of" in entry:
            result.append(tuple(entry["any_of"]))
        else:
            raise ValueError(f"Unrecognized required_skills entry: {entry!r}")
    return tuple(result)


def _load_template(template_dir: Path) -> PredefinedTemplate:
    settings = yaml.safe_load((template_dir / "settings.yaml").read_text(encoding="utf-8"))
    artifacts = {filename[:-3]: _read_artifact(template_dir, filename) for filename in _ARTIFACT_FILES}
    return PredefinedTemplate(
        key=template_dir.name,
        name=settings["name"],
        description=settings["description"],
        soul_md=artifacts["soul"],
        identity_md=artifacts["identity"],
        user_md=artifacts["user"],
        tools_md=artifacts["tools"],
        agents_md=artifacts["agents"],
        boot_md=artifacts["boot"],
        bootstrap_md=artifacts["bootstrap"],
        heartbeat_md=artifacts["heartbeat"],
        required_skill_names=_parse_required_skills(settings.get("required_skills", [])),
    )


def load_predefined_templates() -> tuple[PredefinedTemplate, ...]:
    """Loads every predefined template lineage from `seeds/`, sorted by key for stable ordering."""
    template_dirs = sorted(d for d in SEEDS_DIR.iterdir() if d.is_dir() and d.name != "_defaults")
    return tuple(_load_template(d) for d in template_dirs)
