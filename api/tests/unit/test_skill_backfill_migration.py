"""Backfill helpers from the skill_version/skill_file migration.

The migration's loop only runs against a populated ``skill`` table, which the
integration suite never has (it migrates from empty), so the path-splitting logic
that decides where existing archives land on disk is covered here directly.
"""

import importlib.util
import io
import pathlib
import zipfile

import pytest

_MIGRATION = (
    pathlib.Path(__file__).parents[2]
    / "migrations"
    / "versions"
    / "c7d1e9f4a2b8_add_skill_version_and_skill_file_tables.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("skill_backfill_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _zip(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_readable_entries_skips_archive_metadata():
    blob = _zip({"aai-cli/jira_skill.md": "# Jira", "__MACOSX/._jira_skill.md": "junk"})
    entries, skipped = migration._readable_entries(blob)

    assert entries == [("aai-cli/jira_skill.md", "# Jira")]
    assert skipped == 0


def test_readable_entries_counts_undecodable_entries_instead_of_failing():
    """Binary content was never mountable — the manifest builder always decoded as
    UTF-8 — so it is reported and dropped rather than failing the upgrade."""
    blob = _zip({"SKILL.md": "# Fine", "logo.png": b"\xff\xd8\xff\xe0binary"})
    entries, skipped = migration._readable_entries(blob)

    assert entries == [("SKILL.md", "# Fine")]
    assert skipped == 1


def test_split_root_peels_a_shared_top_level_directory():
    """Today's archives carry their mount directory as the first segment, and root_dir
    now supplies it at mount time, so it must not be stored twice."""
    entries = [("aai-cli/jira_skill.md", "a"), ("aai-cli/helpers/x.md", "b")]
    root, files = migration._split_root(entries, "fallback")

    assert root == "aai-cli"
    assert files == [("jira_skill.md", "a"), ("helpers/x.md", "b")]


def test_split_root_falls_back_when_roots_differ():
    """Without a single shared root, keeping full paths under the skill's own slug is
    what leaves the on-disk layout unchanged."""
    entries = [("docs/a.md", "a"), ("other/b.md", "b")]
    root, files = migration._split_root(entries, "my-skill")

    assert root == "my-skill"
    assert files == entries


def test_split_root_falls_back_when_a_file_sits_at_the_archive_root():
    entries = [("SKILL.md", "a"), ("helpers/x.md", "b")]
    root, files = migration._split_root(entries, "my-skill")

    assert root == "my-skill"
    assert files == entries


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["SKILL.md", "helpers/a.md"], "SKILL.md"),
        (["jira_skill.md"], "jira_skill.md"),
        (["b.md", "a.md"], "a.md"),
        (["notes.txt"], "notes.txt"),
    ],
)
def test_pick_entry_path(paths, expected):
    assert migration._pick_entry_path(paths) == expected


def test_slugify_matches_the_application_helper():
    """The migration cannot import application code, so its copy must not drift."""
    from api.domains.templates.slug import slugify

    for name in ["My Skill", "Google Sheets", "weird__name!!", "Zoho Mail"]:
        assert migration._slugify(name) == slugify(name)
