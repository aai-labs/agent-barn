import pytest

from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOTSTRAP_MD,
    ONBOARDING_TEMPLATE_KEY,
    is_hidden_template_key,
    is_placeholder_bootstrap,
)
from api.domains.templates.predefined.loader import DEFAULTS_DIR, SEEDS_DIR

_DEFAULT_AGENTS_SOURCES = {
    "custom-template default": DEFAULT_AGENTS_MD,
    "predefined seed default": (DEFAULTS_DIR / "agents.md").read_text(),
}


@pytest.mark.parametrize("source", _DEFAULT_AGENTS_SOURCES.values(), ids=_DEFAULT_AGENTS_SOURCES.keys())
def test_default_agents_md_keeps_lessons_where_a_restart_preserves_them(source: str) -> None:
    """Both runtimes copy AGENTS.md and TOOLS.md from configuration on every start and
    rebuild skills from the database, so a lesson written there is silently lost."""
    assert "update AGENTS.md, TOOLS.md, or the relevant skill" not in source
    assert "When you learn a lesson → write it to `MEMORY.md`" in source


def test_onboarding_template_is_the_only_hidden_key() -> None:
    assert ONBOARDING_TEMPLATE_KEY == "trial-onboarding"
    assert is_hidden_template_key(ONBOARDING_TEMPLATE_KEY)


@pytest.mark.parametrize(
    "template_key",
    [
        "general-purpose",
        "scrum-master",
        "code-reviewer",
        "email-reminder",
        "jira-task-helper",
        "documentation-agent",
        "trial-onboarding-copy",
        "",
    ],
)
def test_other_template_keys_are_not_hidden(template_key: str) -> None:
    assert not is_hidden_template_key(template_key)


_PLACEHOLDER_BOOTSTRAPS = {
    "custom-template default": DEFAULT_BOOTSTRAP_MD,
    "predefined seed default": (DEFAULTS_DIR / "bootstrap.md").read_text(encoding="utf-8"),
    "empty": "",
    "whitespace": "  \n\t\n",
    "comment only": "<!-- nothing yet -->",
    "multi-line comment": "<!--\nfill this in\nlater\n-->\n",
    "headings only": "# BOOTSTRAP\n\n## First run\n",
    "headings and comments with CRLF": "# BOOTSTRAP.md\r\n\r\n<!-- Add bootstrap configuration here. -->\r\n",
}


@pytest.mark.parametrize("bootstrap_md", _PLACEHOLDER_BOOTSTRAPS.values(), ids=_PLACEHOLDER_BOOTSTRAPS.keys())
def test_placeholder_bootstraps_are_recognised(bootstrap_md: str) -> None:
    assert is_placeholder_bootstrap(bootstrap_md)


_REAL_BOOTSTRAPS = {
    "onboarding script": (SEEDS_DIR / ONBOARDING_TEMPLATE_KEY / "bootstrap.md").read_text(encoding="utf-8"),
    "text after a heading": "# BOOTSTRAP\n\nGreet the user.\n",
    "text without a heading": "Ask the user their name.",
    "text beside a comment": "<!-- note --> Say hello.",
    "list item": "- Suggest three things to try",
}


@pytest.mark.parametrize("bootstrap_md", _REAL_BOOTSTRAPS.values(), ids=_REAL_BOOTSTRAPS.keys())
def test_real_bootstraps_are_not_placeholders(bootstrap_md: str) -> None:
    assert not is_placeholder_bootstrap(bootstrap_md)
