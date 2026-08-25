import json

from api.domains.agents.gog_artifacts import (
    _SERVICE_GUIDE,
    build_gog_env,
    build_gog_policy_md,
    build_gog_setup_sh,
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
_SCOPES = _FULL_SCOPES


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


def test_env_carries_every_key_gog_setup_needs():
    env = build_gog_env(_content(), "/home/node", "kr-pass")
    assert set(env) == {
        "GOG_HOME",
        "GOG_KEYRING_BACKEND",
        "GOG_KEYRING_PASSWORD",
        "GOG_CLIENT_JSON",
        "GOG_TOKEN_JSON",
        "GOG_ACCOUNT_EMAIL",
    }


def test_env_uses_file_keyring_with_the_given_password():
    # The file backend is what makes gog usable headless; the password is generated per
    # start by the caller, so the builder must pass it through untouched.
    env = build_gog_env(_content(), "/home/node", "kr-pass")
    assert env["GOG_KEYRING_BACKEND"] == "file"
    assert env["GOG_KEYRING_PASSWORD"] == "kr-pass"


def test_env_gog_home_follows_the_runtime_home_dir():
    assert build_gog_env(_content(), "/home/node", "p")["GOG_HOME"] == "/home/node/.config/gogcli"
    assert build_gog_env(_content(), "/home/hermes", "p")["GOG_HOME"] == "/home/hermes/.config/gogcli"


def test_gog_home_is_not_the_hermes_pvc():
    # Deliberately the container filesystem: the keyring is a per-boot cache of the DB
    # row, and start_agent's aai_home (/opt/data for Hermes) must not be reused here.
    assert not gog_home("/home/hermes").startswith("/opt/data")


def test_env_client_json_is_a_web_client_gog_can_read():
    env = build_gog_env(_content(), "/home/node", "p")
    assert json.loads(env["GOG_CLIENT_JSON"]) == {
        "web": {
            "client_id": "client-id.apps.googleusercontent.com",
            "client_secret": "GOCSPX-secret",
        }
    }


def test_env_token_json_matches_the_gog_import_schema():
    env = build_gog_env(_content(), "/home/node", "p")
    assert json.loads(env["GOG_TOKEN_JSON"]) == {
        "email": "user@example.com",
        "client": "default",
        "services": ["gmail", "calendar"],
        "scopes": _SCOPES,
        "refresh_token": "rt-123",
    }


def test_env_account_email_matches_the_credential():
    assert build_gog_env(_content(), "/home/node", "p")["GOG_ACCOUNT_EMAIL"] == "user@example.com"


# --- setup script ---


def test_setup_sh_rebuilds_state_from_scratch():
    script = build_gog_setup_sh()
    # Wiping first is what makes a removed or changed credential take effect on restart.
    assert 'rm -rf "$GOG_HOME"' in script
    assert 'mkdir -p "$GOG_HOME"' in script
    assert "umask 077" in script


def test_setup_sh_installs_client_and_imports_token():
    script = build_gog_setup_sh()
    assert "gog auth credentials" in script
    assert "gog auth tokens import -" in script


def test_setup_sh_removes_the_temporary_client_file():
    assert 'rm -f "$client_file"' in build_gog_setup_sh()


def test_setup_sh_does_not_set_a_default_alias():
    # "default" is a reserved alias name in gog; with exactly one imported token the
    # account is inferred, so setting one would only ever fail the boot.
    assert "alias set" not in build_gog_setup_sh()


def test_setup_sh_holds_no_secret_material():
    # It ships in the ConfigMap, so everything sensitive must arrive via env.
    script = build_gog_setup_sh()
    for secret in ("rt-123", "GOCSPX-secret", "user@example.com"):
        assert secret not in script


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
