from api.domains.agents.runtime_digest import (
    agent_runtime_config_digest,
    asset_files,
    discover_closure,
    normalize_python_source,
)

_POLICY_SOURCE = '''"""Module docstring."""

_POLICY_MD = """
## Role Scope

Out of scope: ASCII art.
"""


def build_policy_md() -> str:
    """Return the policy block."""
    return _POLICY_MD
'''

_ASSEMBLY_METHODS = {
    "_provision_and_start",
    "_auto_attached_aai_cli_skills",
    "_build_skill_pointers",
    "_native_slack_connection",
    "_native_connection_configuration",
    "_backfill_google_client_credentials",
}


def _service_methods(closure):
    return {
        symbol.removeprefix("AgentService.")
        for module, symbol in closure
        if module == "api.domains.agents.service" and symbol.startswith("AgentService.")
    }


def test_digest_is_stable_across_calls():
    assert agent_runtime_config_digest("openclaw:1", "hermes:1") == agent_runtime_config_digest(
        "openclaw:1", "hermes:1"
    )


def test_digest_is_a_sha256_hex_string():
    digest = agent_runtime_config_digest("openclaw:1", "hermes:1")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_digest_changes_when_the_openclaw_image_changes():
    assert agent_runtime_config_digest("openclaw:2", "hermes:1") != agent_runtime_config_digest(
        "openclaw:1", "hermes:1"
    )


def test_digest_changes_when_the_hermes_image_changes():
    assert agent_runtime_config_digest("openclaw:1", "hermes:2") != agent_runtime_config_digest(
        "openclaw:1", "hermes:1"
    )


def test_normalization_ignores_added_comments():
    edited = _POLICY_SOURCE.replace("def build_policy_md", "# reviewer asked for a note\ndef build_policy_md")
    assert normalize_python_source(edited) == normalize_python_source(_POLICY_SOURCE)


def test_normalization_ignores_reformatting_outside_string_literals():
    edited = _POLICY_SOURCE.replace("def build_policy_md", "\n\ndef build_policy_md")
    assert normalize_python_source(edited) == normalize_python_source(_POLICY_SOURCE)


def test_normalization_ignores_carriage_returns():
    assert normalize_python_source(_POLICY_SOURCE.replace("\n", "\r\n")) == normalize_python_source(_POLICY_SOURCE)


def test_normalization_ignores_module_docstrings():
    edited = _POLICY_SOURCE.replace('"""Module docstring."""', '"""Reworded module docstring."""')
    assert normalize_python_source(edited) == normalize_python_source(_POLICY_SOURCE)


def test_normalization_ignores_function_docstrings():
    edited = _POLICY_SOURCE.replace('"""Return the policy block."""', '"""Return the policy markdown."""')
    assert normalize_python_source(edited) == normalize_python_source(_POLICY_SOURCE)


def test_normalization_detects_changed_policy_text():
    edited = _POLICY_SOURCE.replace("Out of scope", "Outside of scope")
    assert normalize_python_source(edited) != normalize_python_source(_POLICY_SOURCE)


def test_normalization_detects_a_renamed_definition():
    edited = _POLICY_SOURCE.replace("build_policy_md", "build_role_policy_md")
    assert normalize_python_source(edited) != normalize_python_source(_POLICY_SOURCE)


def test_closure_covers_exactly_the_assembly_methods():
    assert _service_methods(discover_closure()) == _ASSEMBLY_METHODS


def test_closure_covers_the_runtime_builders():
    modules = {module for module, _ in discover_closure()}
    assert "api.domains.agents.builders.openclaw" in modules
    assert "api.domains.agents.builders.hermes" in modules


def test_closure_covers_the_policy_and_artifact_modules():
    modules = {module for module, _ in discover_closure()}
    assert "api.domains.agents.runtime_policy" in modules
    assert "api.domains.agents.aai_cli_artifacts" in modules
    assert "api.domains.agents.gog_artifacts" in modules
    assert "api.domains.templates.renderer" in modules


def test_closure_covers_injected_collaborators():
    modules = {module for module, _ in discover_closure()}
    assert "api.domains.agent_settings.lookup" in modules
    assert "api.infrastructure.kubernetes.client" in modules


def test_closure_covers_symbols_reached_only_through_collaborators():
    symbols = {symbol for _, symbol in discover_closure()}
    assert "AgentSettingsLookupService.resolve_default_model" in symbols
    assert "TemplateRepository.get_pinned_template" in symbols


def test_asset_files_exclude_bytecode_caches():
    assert all("__pycache__" not in path.parts for path in asset_files())


def test_asset_files_cover_both_runtime_script_trees():
    names = {path.name for path in asset_files()}
    assert "start.sh" in names
    assert "init-openclaw.js" in names
    assert "bootloader-footer.md" in names
    assert "SKILL.md" in names
