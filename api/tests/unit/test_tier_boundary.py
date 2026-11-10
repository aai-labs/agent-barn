"""Only the tiers domain knows about Tiers.

Other domains ask the `UsageGuard` whether an action is allowed and read an Organization's
plan through it, and start new Organizations through `OrganizationPlans`. They never import
`api.domains.tiers`. Subscriptions change an Organization's Tier, so they may.
"""

import ast
from pathlib import Path

from hamcrest import assert_that, empty

DOMAINS = Path(__file__).resolve().parents[2] / "domains"
TIERS = "api.domains.tiers"

_ALLOWED_DOMAINS = {"tiers", "subscriptions"}


def _imports_tiers(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(TIERS):
            return True
        if isinstance(node, ast.Import) and any(alias.name.startswith(TIERS) for alias in node.names):
            return True
    return False


def _importers() -> set[str]:
    found = set()
    for path in DOMAINS.rglob("*.py"):
        relative = path.relative_to(DOMAINS)
        if relative.parts[0] in _ALLOWED_DOMAINS:
            continue
        if _imports_tiers(path):
            found.add(relative.as_posix())
    return found


def test_no_other_domain_imports_tiers():
    assert_that(sorted(_importers()), empty())
