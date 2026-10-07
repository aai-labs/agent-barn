from pathlib import Path

from api.domains.agents.aai_cli_skills import _BUNDLED_ROOT, _COMMANDS
from api.domains.business_value.catalogue import (
    CATALOGUE,
    DEFAULT_MINUTES,
    GLOBAL_FLAGS,
    CommandKind,
    OutcomeType,
    deepest_node,
    longest_match,
)

_REFERENCE_NAME = "references/command-reference.md"
_MICROSOFT_REFERENCE_DIR = "aai-microsoft"
_EXPECTED_REFERENCE_COUNT = 13


def _reference_files() -> dict[str, Path]:
    return {path.parent.parent.name: path for path in sorted(_BUNDLED_ROOT.glob(f"*/{_REFERENCE_NAME}"))}


def _strip_global_flags(tokens: list[str]) -> list[str]:
    kept: list[str] = []
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
            continue
        if token in GLOBAL_FLAGS:
            skip_value = True
            continue
        if token.split("=", 1)[0] in GLOBAL_FLAGS and "=" in token:
            continue
        kept.append(token)
    return kept


def _command_lines(skill_dir: str, reference: Path) -> list[tuple[int, list[str]]]:
    prefix = "microsoft " if skill_dir == _MICROSOFT_REFERENCE_DIR else "aai-cli "
    lines = []
    for number, line in enumerate(reference.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith(prefix):
            continue
        tokens = _strip_global_flags(line.split())
        if prefix == "aai-cli ":
            tokens = tokens[1:]
        lines.append((number, tokens))
    return lines


def _is_placeholder(tokens: list[str]) -> bool:
    node = deepest_node(tokens)
    return len(tokens) > len(node) and tokens[len(node)].startswith("<")


def test_catalogue_integrations_equal_bundled_command_groups():
    assert {path[0] for path in CATALOGUE} == set(_COMMANDS.values())


def test_every_bundled_command_path_is_covered_by_the_catalogue():
    references = _reference_files()
    assert len(references) == _EXPECTED_REFERENCE_COUNT
    assert set(references) == set(_COMMANDS)

    uncovered = []
    for skill_dir, reference in references.items():
        for number, tokens in _command_lines(skill_dir, reference):
            if longest_match(tokens) is not None or _is_placeholder(tokens):
                continue
            uncovered.append(f"{skill_dir}:{number}: {' '.join(tokens)}")

    assert uncovered == []


def test_every_reference_contributes_command_lines():
    for skill_dir, reference in _reference_files().items():
        assert _command_lines(skill_dir, reference), f"{skill_dir} has no command lines"


def test_every_write_path_has_an_outcome_type():
    missing = [
        " ".join(path)
        for path, entry in CATALOGUE.items()
        if entry.kind is CommandKind.WRITE and entry.outcome_type is None
    ]
    assert missing == []


def test_only_writes_carry_an_outcome_type():
    stray = [
        " ".join(path)
        for path, entry in CATALOGUE.items()
        if entry.kind is not CommandKind.WRITE and entry.outcome_type is not None
    ]
    assert stray == []


def test_every_outcome_type_has_default_minutes():
    assert set(DEFAULT_MINUTES) == set(OutcomeType)
    assert all(minutes > 0 for minutes in DEFAULT_MINUTES.values())


def test_longest_match_prefers_the_deepest_command_path():
    match = longest_match(["jira", "issues", "comments", "create", "ABC-1"])

    assert match is not None
    path, entry = match
    assert path == ("jira", "issues", "comments", "create")
    assert entry.outcome_type is OutcomeType.COMMENT_POSTED


def test_longest_match_returns_none_for_an_unknown_path():
    assert longest_match(["jira", "issues", "transition", "ABC-1"]) is None
    assert deepest_node(["jira", "issues", "transition", "ABC-1"]) == ("jira", "issues")
