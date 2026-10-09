from api.domains.agents.gog_artifacts import (
    _SERVICE_GUIDE,
    build_gog_policy_md,
    gog_home,
)
from api.domains.agents.models import GOOGLE_WORKSPACE_SERVICES, GoogleWorkspaceContent
from api.domains.integrations.google_oauth.routes import _WORKSPACE_SERVICE_SCOPES

_FULL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.settings.sharing",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
_READ_ONLY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def _content(**overrides) -> GoogleWorkspaceContent:
    defaults = {
        "email": "user@example.com",
        "services": ["gmail", "calendar"],
        "scopes": _READ_ONLY_SCOPES if overrides.get("read_only", False) else _FULL_SCOPES,
        "refresh_token": "rt-123",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "GOCSPX-secret",
    }
    defaults.update(overrides)
    return GoogleWorkspaceContent.model_validate(defaults)


# --- service maps ---


def test_google_workspace_service_maps_have_matching_keys():
    assert set(GOOGLE_WORKSPACE_SERVICES) == set(_WORKSPACE_SERVICE_SCOPES) == set(_SERVICE_GUIDE)


# --- env ---
#
# build_gog_env and the shim are covered in test_google_workspace_broker.py, alongside
# the mint that produces the token they carry.


def test_gog_home_is_not_the_hermes_pvc():
    # Deliberately the container filesystem: gog's state is a per-boot cache, and
    # start_agent's aai_home (/opt/data for Hermes) must not be reused here.
    assert not gog_home("/home/hermes").startswith("/opt/data")


# --- agent policy block ---


def test_policy_md_is_empty_without_a_credential():
    assert build_gog_policy_md(None) == ""


def test_policy_md_names_the_account_and_services():
    md = build_gog_policy_md(_content())
    assert "## Google Workspace (gog)" in md
    assert "user@example.com" in md
    assert "Gmail" in md
    assert "Calendar" in md


def test_policy_md_omits_services_that_were_not_granted():
    md = build_gog_policy_md(_content(services=["gmail"]))
    assert "Gmail" in md
    assert "Calendar" not in md
    assert "Drive" not in md


def test_policy_md_teaches_the_command_grammar_with_examples():
    md = build_gog_policy_md(_content(services=["gmail", "drive"]))
    assert "gog <service> <resource> <verb>" in md
    assert "gog gmail search" in md
    assert "gog drive files list" in md


def test_policy_md_separates_gog_from_aai_cli():
    # The aai-cli block insists on --profile and on being the only route to its
    # integrations; an agent must not apply either rule to gog.
    md = build_gog_policy_md(_content())
    assert "separate tool from aai-cli" in md
    assert "no `--profile`" in md


def test_policy_md_flags_read_only_credentials():
    assert "read-only" in build_gog_policy_md(_content(read_only=True))
    assert "read-only" not in build_gog_policy_md(_content(read_only=False))


def test_policy_md_forbids_browser_and_credential_prompts():
    md = build_gog_policy_md(_content())
    assert "never ask the user" in md.lower()
    assert "browser" in md
