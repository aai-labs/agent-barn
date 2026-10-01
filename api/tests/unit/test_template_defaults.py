import pytest

from api.domains.templates.defaults import DEFAULT_AGENTS_MD
from api.domains.templates.predefined.loader import DEFAULTS_DIR

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
