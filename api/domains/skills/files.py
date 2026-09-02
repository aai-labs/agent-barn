"""Skill file path rules, shared by the skill service, the built-in seeder and the
migration backfill.

Skill content is a flat list of (path, content) pairs where ``path`` is relative to
the skill's root directory. This module is the single place that decides whether a
path is safe to write under ./skills in an agent workspace; it raises ``ValueError``
so callers can map it to their own error surface (HTTP 400, a migration warning, a
seeder assertion) without this module depending on FastAPI.
"""

import re
from collections.abc import Sequence

DEFAULT_ENTRY_PATH = "SKILL.md"

MAX_FILES = 200
MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB per file
MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5 MB per version

_MAX_PATH_LENGTH = 512
# Archive noise that must never reach a workspace. Previously filtered at mount
# time; now rejected at the boundary so it never enters the database.
_JUNK_PREFIXES = ("__MACOSX/", "._")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_path(raw: str) -> str:
    """Return a validated POSIX path relative to the skill root.

    Raises ValueError with a user-facing message when the path is unusable.
    """
    path = raw.strip().replace("\\", "/")
    path = path.removeprefix("./")
    # Collapse duplicate slashes: "a//b" and "a/b" address the same file.
    while "//" in path:
        path = path.replace("//", "/")

    if not path:
        raise ValueError("File path cannot be empty")
    if len(path) > _MAX_PATH_LENGTH:
        raise ValueError(f"File path exceeds {_MAX_PATH_LENGTH} characters: {raw!r}")
    if path.startswith("/"):
        raise ValueError(f"File path must be relative, not absolute: {raw!r}")
    if path.endswith("/"):
        raise ValueError(f"File path must name a file, not a directory: {raw!r}")

    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError(f"File path contains an invalid segment: {raw!r}")
        if not _SEGMENT_RE.match(segment):
            raise ValueError(f"File path may only contain letters, digits, dots, dashes and underscores: {raw!r}")
    if path.startswith(_JUNK_PREFIXES) or any(s.startswith("._") for s in segments):
        raise ValueError(f"File path is archive metadata, not skill content: {raw!r}")

    return path


def validate_files(files: Sequence[tuple[str, str]], *, entry_path: str = DEFAULT_ENTRY_PATH) -> list[tuple[str, str]]:
    """Normalize and validate a full set of Skill files.

    Every published Skill version has exactly one root ``SKILL.md`` entry point.
    Legacy custom entry names are normalized by the migration before they reach
    this boundary; callers cannot create another entry-point convention.
    Returns the normalized list sorted by path.
    """
    if entry_path != DEFAULT_ENTRY_PATH:
        raise ValueError(f"A skill's entry-point file must be {DEFAULT_ENTRY_PATH!r}")
    if not files:
        raise ValueError("A skill must contain at least one file")
    if len(files) > MAX_FILES:
        raise ValueError(f"A skill may contain at most {MAX_FILES} files")

    normalized: list[tuple[str, str]] = []
    # Authors on macOS routinely produce paths differing only in case; the agent
    # workspace is Linux, so those would land as two files that look identical.
    seen: dict[str, str] = {}
    total = 0

    for raw_path, content in files:
        path = normalize_path(raw_path)
        lowered = path.lower()
        if lowered in seen:
            raise ValueError(f"Duplicate file path (paths are case-insensitive): {path!r} and {seen[lowered]!r}")
        seen[lowered] = path

        size = len(content.encode())
        if size > MAX_FILE_BYTES:
            raise ValueError(f"File {path!r} exceeds the 1 MB per-file limit")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Skill content exceeds the 5 MB total limit")

        normalized.append((path, content))

    if not any(p == DEFAULT_ENTRY_PATH for p, _ in normalized):
        raise ValueError(f"A skill must include its entry-point file {DEFAULT_ENTRY_PATH!r}")

    return sorted(normalized, key=lambda pair: pair[0])
