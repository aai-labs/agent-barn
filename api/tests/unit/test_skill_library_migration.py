"""Pure migration guards for the completed Skill library migration."""

import importlib.util
import pathlib

import pytest

_MIGRATION = (
    pathlib.Path(__file__).parents[2] / "migrations" / "versions" / "b6c7d8e9f0a1_complete_skill_library_model.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("complete_skill_library_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_entry_selection_prefers_the_canonical_root_file():
    assert migration._choose_entry_path("Jira", "skill-id", "jira_skill.md", ["SKILL.md", "notes.md"]) == "SKILL.md"


def test_entry_selection_uses_the_legacy_entry_when_present():
    assert migration._choose_entry_path("Jira", "skill-id", "jira_skill.md", ["jira_skill.md"]) == "jira_skill.md"


def test_entry_selection_fails_with_the_repair_guidance_when_missing():
    with pytest.raises(RuntimeError, match="repair the legacy content before retrying"):
        migration._choose_entry_path("Broken", "skill-id", "legacy.txt", ["notes.txt"])


def test_entry_selection_fails_when_multiple_markdown_candidates_are_ambiguous():
    with pytest.raises(RuntimeError, match="multiple SKILL.md candidates"):
        migration._choose_entry_path("Ambiguous", "skill-id", "legacy.txt", ["a.md", "b.md"])


def test_mount_references_are_rewritten_to_the_isolated_bundle_root():
    content = "Read ./skills/aai-cli/jira_skill.md and skills/aai-cli/jira_skill.md."
    assert migration._replace_mount_references(content, "aai-cli", "jira_skill.md", "aai-jira") == (
        "Read ./skills/aai-jira/SKILL.md and skills/aai-jira/SKILL.md."
    )


def test_normalized_mount_slug_collisions_fail_before_unique_indexes_are_created():
    rows = [
        {
            "id": "platform-one",
            "organization_id": None,
            "agent_id": None,
            "name": "Jira",
            "slug": "jira",
            "source": "aai_cli",
        },
        {
            "id": "platform-two",
            "organization_id": None,
            "agent_id": None,
            "name": "Jira Custom",
            "slug": "aai-jira",
            "source": "custom",
        },
    ]

    with pytest.raises(RuntimeError, match="duplicate normalized mount slugs"):
        migration._check_normalized_slug_collisions(rows)
