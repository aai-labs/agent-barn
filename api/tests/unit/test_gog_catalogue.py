import json
import re
from pathlib import Path
from typing import Any

import pytest
from hamcrest import assert_that, equal_to, has_length, is_, none, not_none

from api.domains.agents.models import GOOGLE_WORKSPACE_SERVICES
from api.domains.business_value.catalogue import DEFAULT_MINUTES, CommandKind
from api.domains.business_value.gog_catalogue import (
    GOG_ALIASES,
    GOG_CATALOGUE,
    GOG_IGNORED_COMMANDS,
    GOG_INTEGRATIONS,
    GOG_SERVICES,
    GOG_SHORTCUTS,
    GOG_TOP_LEVEL_ALIASES,
    GOG_VALUE_FLAGS,
    gog_longest_match,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMAND_TREE = Path(__file__).resolve().parents[1] / "fixtures" / "gog" / "command-tree.json"
_DOCKERFILES = (_REPO_ROOT / "hermes-base" / "Dockerfile", _REPO_ROOT / "openclaw-base" / "Dockerfile")
_GOG_VERSION_ARG = re.compile(r"^ARG GOG_VERSION=(\S+)$", re.MULTILINE)
_SHORTCUT_HELP = re.compile(r"\(alias for '([^']+)'\)")
_STRING_FLAG_TYPE = "string"
_EXPECTED_LEAF_COUNT = 209
_EXPECTED_SHORTCUT_COUNT = 5


def _tree() -> dict[str, Any]:
    return json.loads(_COMMAND_TREE.read_text(encoding="utf-8"))


def _leaves(node: dict[str, Any], path: tuple[str, ...]) -> list[tuple[str, ...]]:
    here = (*path, node["name"])
    children = node.get("subcommands") or []
    if not children:
        return [here]
    return [leaf for child in children for leaf in _leaves(child, here)]


def _alias_tables(node: dict[str, Any], path: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    here = (*path, node["name"])
    children = node.get("subcommands") or []
    tables: dict[tuple[str, ...], dict[str, str]] = {}
    aliases = {alias: child["name"] for child in children for alias in child["aliases"]}
    if aliases:
        tables[here] = aliases
    for child in children:
        tables.update(_alias_tables(child, here))
    return tables


def _pinned_versions() -> set[str]:
    versions = set()
    for dockerfile in _DOCKERFILES:
        found = _GOG_VERSION_ARG.findall(dockerfile.read_text(encoding="utf-8"))
        assert_that(found, has_length(1))
        versions.add(found[0])
    return versions


def test_the_command_tree_was_recorded_from_the_pinned_gog_version():
    versions = _pinned_versions()

    assert_that(versions, has_length(1))
    assert_that(_tree()["build"].startswith(f"v{versions.pop()} "), is_(True))


def test_granted_services_are_the_google_workspace_credential_services():
    assert_that(set(GOG_SERVICES), equal_to(set(GOOGLE_WORKSPACE_SERVICES)))
    assert_that(GOG_INTEGRATIONS, equal_to(frozenset(f"google-{service}" for service in GOOGLE_WORKSPACE_SERVICES)))


def test_the_catalogue_covers_exactly_the_granted_service_commands():
    leaves = {leaf for service in _tree()["services"] for leaf in _leaves(service, ())}

    assert_that(leaves, has_length(_EXPECTED_LEAF_COUNT))
    assert_that(set(GOG_CATALOGUE), equal_to(leaves))


def test_command_aliases_match_the_command_tree():
    tables: dict[tuple[str, ...], dict[str, str]] = {}
    for service in _tree()["services"]:
        tables.update(_alias_tables(service, ()))

    assert_that(GOG_ALIASES, equal_to(tables))


def test_top_level_aliases_match_the_command_tree():
    aliases = {alias: command["name"] for command in _tree()["top_level"] for alias in command["aliases"]}

    assert_that(GOG_TOP_LEVEL_ALIASES, equal_to(aliases))


def test_shortcuts_match_the_command_tree():
    shortcuts = {}
    for command in _tree()["top_level"]:
        match = _SHORTCUT_HELP.search(command["help"])
        if match is not None and match.group(1).split()[0] in GOG_SERVICES:
            shortcuts[command["name"]] = tuple(match.group(1).split())

    assert_that(shortcuts, has_length(_EXPECTED_SHORTCUT_COUNT))
    assert_that(GOG_SHORTCUTS, equal_to(shortcuts))
    for path in GOG_SHORTCUTS.values():
        assert_that(GOG_CATALOGUE.get(path), not_none())


def test_ignored_commands_are_top_level_commands():
    names = {command["name"] for command in _tree()["top_level"]}

    assert_that(GOG_IGNORED_COMMANDS - names, equal_to(set()))
    assert_that(GOG_IGNORED_COMMANDS & set(GOG_SERVICES), equal_to(set()))


def test_value_flags_are_the_global_flags_that_take_a_value():
    expected = set()
    for flag in _tree()["global_flags"]:
        if flag["type"] == _STRING_FLAG_TYPE:
            expected.add(f"--{flag['name']}")
            if flag["short"]:
                expected.add(f"-{flag['short']}")

    assert_that(GOG_VALUE_FLAGS, equal_to(frozenset(expected)))


def test_every_write_has_an_outcome_type_with_default_minutes():
    for path, entry in GOG_CATALOGUE.items():
        if entry.kind is CommandKind.WRITE:
            assert entry.outcome_type is not None, path
            assert entry.outcome_type in DEFAULT_MINUTES, path


def test_only_writes_carry_an_outcome_type():
    for path, entry in GOG_CATALOGUE.items():
        if entry.kind is not CommandKind.WRITE:
            assert entry.outcome_type is None, path


def test_the_catalogue_has_no_passthrough_commands():
    assert_that(
        {entry.kind for entry in GOG_CATALOGUE.values()} - {CommandKind.READ, CommandKind.WRITE, CommandKind.IGNORED},
        equal_to(set()),
    )


@pytest.mark.parametrize(
    ("tokens", "expected_path"),
    [
        (["gmail", "send", "--to", "x"], ("gmail", "send")),
        (["mail", "labels", "ls"], ("gmail", "labels", "list")),
        (["email", "drafts", "new"], ("gmail", "drafts", "create")),
        (["drv", "rm", "file-id"], ("drive", "delete")),
        (["cal", "add", "primary"], ("calendar", "create")),
        (["sheet", "add", "id", "A1"], ("sheets", "append")),
        (["gmail", "settings", "filters", "ls"], ("gmail", "settings", "filters", "list")),
    ],
)
def test_longest_match_follows_aliases_to_the_canonical_path(tokens, expected_path):
    match = gog_longest_match(tokens)

    assert match is not None
    assert_that(match[0], equal_to(expected_path))


def test_longest_match_returns_none_for_an_unknown_path():
    assert_that(gog_longest_match(["gmail", "no-such-command"]), none())
