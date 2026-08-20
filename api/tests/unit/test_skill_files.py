"""Path rules for skill files.

These replace the old zip-archive checks: content now arrives as (path, content)
pairs, so the boundary that used to reject malicious archives rejects malicious
paths instead.
"""

import pytest

from api.domains.skills.files import MAX_FILE_BYTES, MAX_FILES, normalize_path, validate_files


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SKILL.md", "SKILL.md"),
        ("./SKILL.md", "SKILL.md"),
        ("helpers/one.md", "helpers/one.md"),
        ("helpers//one.md", "helpers/one.md"),
        ("  SKILL.md  ", "SKILL.md"),
        ("helpers\\one.md", "helpers/one.md"),
    ],
)
def test_normalize_path_accepts_and_normalizes(raw, expected):
    assert normalize_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "../outside.md",
        "helpers/../../outside.md",
        "helpers/",
        "",
        "   ",
        "__MACOSX/junk.md",
        "._resource",
        "helpers/._resource",
        "file with spaces.md",
        "weird$char.md",
    ],
)
def test_normalize_path_rejects_unsafe_paths(raw):
    with pytest.raises(ValueError):
        normalize_path(raw)


def test_validate_files_sorts_by_path():
    files = validate_files(
        [("helpers/b.md", "b"), ("SKILL.md", "root"), ("helpers/a.md", "a")],
        entry_path="SKILL.md",
    )
    assert [path for path, _ in files] == ["SKILL.md", "helpers/a.md", "helpers/b.md"]


def test_validate_files_requires_the_entry_point():
    with pytest.raises(ValueError, match="entry-point"):
        validate_files([("helpers/a.md", "a")], entry_path="SKILL.md")


def test_validate_files_allows_omitting_the_entry_point_check():
    """Built-ins name their own entry file, so the check is caller-supplied."""
    files = validate_files([("jira_skill.md", "docs")])
    assert files == [("jira_skill.md", "docs")]


def test_validate_files_rejects_case_insensitive_duplicates():
    """The workspace is Linux but authors are often on macOS, where these two paths
    are the same file."""
    with pytest.raises(ValueError, match="Duplicate file path"):
        validate_files([("SKILL.md", "a"), ("skill.md", "b")])


def test_validate_files_rejects_paths_that_normalize_to_the_same_file():
    with pytest.raises(ValueError, match="Duplicate file path"):
        validate_files([("SKILL.md", "a"), ("./SKILL.md", "b")])


def test_validate_files_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one file"):
        validate_files([])


def test_validate_files_rejects_too_many_files():
    files = [(f"f{i}.md", "x") for i in range(MAX_FILES + 1)]
    with pytest.raises(ValueError, match="at most"):
        validate_files(files)


def test_validate_files_rejects_oversized_file():
    with pytest.raises(ValueError, match="per-file limit"):
        validate_files([("SKILL.md", "x" * (MAX_FILE_BYTES + 1))])


def test_validate_files_rejects_oversized_total():
    # Each file is individually legal; only the sum crosses the limit.
    files = [(f"f{i}.md", "x" * (MAX_FILE_BYTES - 1)) for i in range(6)]
    with pytest.raises(ValueError, match="total limit"):
        validate_files(files)


def test_validate_files_measures_size_in_bytes_not_characters():
    """A multi-byte character must count for its encoded length, or the cap is a
    third of what it claims for non-ASCII content."""
    content = "é" * (MAX_FILE_BYTES // 2 + 1)  # 2 bytes each
    with pytest.raises(ValueError, match="per-file limit"):
        validate_files([("SKILL.md", content)])
