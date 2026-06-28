from api.domains.agents.aai_cli_artifacts import (
    CONFIG_PATH,
    build_config_toml,
    build_env,
    build_setup_sh,
    env_var_for,
)
from api.domains.agents.models import SecretProvider, validate_content

_GITHUB = validate_content(
    SecretProvider.GITHUB,
    {"token": "ghp_tok", "owner": "aai-labs", "repo": "agent-farm", "org": "aai-labs"},
)
_JIRA = validate_content(
    SecretProvider.JIRA,
    {
        "site_url": "https://x.atlassian.net",
        "email": "a@b.com",
        "api_token": "jira_tok",
    },
)
_CONFLUENCE = validate_content(
    SecretProvider.CONFLUENCE,
    {
        "site_url": "https://x.atlassian.net",
        "email": "a@b.com",
        "api_token": "conf_tok",
    },
)
_GMAIL = validate_content(
    SecretProvider.GMAIL,
    {
        "client_id": "132806748841-abc.apps.googleusercontent.com",
        "client_secret": "g_client_secret",
        "refresh_token": "g_refresh_tok",
    },
)
_ZOHO_MAIL = validate_content(
    SecretProvider.ZOHO_MAIL,
    {
        "email": "samuel@aai-labs.com",
        "account_id": "56218000000008002",
        "client_id": "1000.WNPJ721D9UHU9SIHFSU4WA2P04W9LI",
        "client_secret": "z_client_secret",
        "refresh_token": "z_refresh_tok",
    },
)
_GOOGLE_CALENDAR = validate_content(
    SecretProvider.GOOGLE_CALENDAR,
    {"access_token": "gc_tok", "calendar_id": "primary"},
)


def test_env_var_for():
    assert env_var_for("jira.api_token") == "AAI_SECRET_JIRA_API_TOKEN"
    assert env_var_for("github.token") == "AAI_SECRET_GITHUB_TOKEN"
    assert env_var_for("google.client_secret") == "AAI_SECRET_GOOGLE_CLIENT_SECRET"
    assert env_var_for("google.gmail_refresh_token") == "AAI_SECRET_GOOGLE_GMAIL_REFRESH_TOKEN"
    assert env_var_for("zoho.client_secret") == "AAI_SECRET_ZOHO_CLIENT_SECRET"
    assert env_var_for("zoho.mail_refresh_token") == "AAI_SECRET_ZOHO_MAIL_REFRESH_TOKEN"


def test_config_toml_emits_only_present_store_profiles():
    toml = build_config_toml(
        {
            SecretProvider.JIRA: _JIRA,
            SecretProvider.CONFLUENCE: _CONFLUENCE,
            SecretProvider.GITHUB: _GITHUB,
        }
    )
    assert 'secrets_file = "/home/node/.config/aai-cli/aai-secrets.enc.json"' in toml
    assert 'key_file = "/home/node/.config/aai-cli/key"' in toml
    assert "[profiles.jira-work]" in toml
    assert "[profiles.confluence-work]" in toml
    assert "[profiles.github-work]" in toml
    assert "[profiles.bitbucket-work]" not in toml
    assert "[profiles.gmail-work]" not in toml
    assert 'api_token_secret = "jira.api_token"' in toml
    assert 'token_secret = "github.token"' in toml
    assert 'site_url = "https://x.atlassian.net"' in toml
    assert 'owner = "aai-labs"' in toml
    # token values never appear in the config
    assert "jira_tok" not in toml
    assert "ghp_tok" not in toml


def test_config_toml_gmail_uses_secret_store():
    toml = build_config_toml({SecretProvider.GMAIL: _GMAIL})
    assert "[profiles.gmail-work]" in toml
    assert 'provider = "google"' in toml
    assert 'auth_type = "bearer_token"' in toml
    assert f'client_id = "{_GMAIL.client_id}"' in toml
    assert 'client_secret_secret = "google.client_secret"' in toml
    assert 'refresh_token_secret = "google.gmail_refresh_token"' in toml
    assert 'user_id = "me"' in toml
    # secret values must not appear in the config
    assert "g_client_secret" not in toml
    assert "g_refresh_tok" not in toml
    assert "token_env" not in toml


def test_config_toml_zoho_mail_uses_oauth_rest_profile():
    toml = build_config_toml({SecretProvider.ZOHO_MAIL: _ZOHO_MAIL})
    assert "[profiles.zoho-mail-rest]" in toml
    assert 'provider = "zoho"' in toml
    assert 'auth_type = "zoho_oauth"' in toml
    assert f'email = "{_ZOHO_MAIL.email}"' in toml
    assert f'account_id = "{_ZOHO_MAIL.account_id}"' in toml
    assert f'client_id = "{_ZOHO_MAIL.client_id}"' in toml
    assert 'client_secret_secret = "zoho.client_secret"' in toml
    assert 'refresh_token_secret = "zoho.mail_refresh_token"' in toml
    # secret values must not appear in the config
    assert "z_client_secret" not in toml
    assert "z_refresh_tok" not in toml
    # must not generate the old smtp_imap profile
    assert "zoho-mail-work" not in toml
    assert "smtp_imap" not in toml


def test_setup_sh_cp_always_and_secrets_set_per_store_provider():
    setup = build_setup_sh([SecretProvider.JIRA, SecretProvider.GITHUB])
    assert f"cp /app/config/aai-cli-config.toml {CONFIG_PATH}" in setup
    assert (
        f"printf '%s' \"$AAI_SECRET_JIRA_API_TOKEN\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set jira.api_token" in setup
    )
    assert "secrets set github.token" in setup
    assert "jira_tok" not in setup


def test_setup_sh_gmail_sets_both_secrets():
    setup = build_setup_sh([SecretProvider.GMAIL])
    assert (
        f"printf '%s' \"$AAI_SECRET_GOOGLE_CLIENT_SECRET\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set google.client_secret" in setup
    )
    assert (
        f"printf '%s' \"$AAI_SECRET_GOOGLE_GMAIL_REFRESH_TOKEN\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set google.gmail_refresh_token" in setup
    )


def test_setup_sh_zoho_mail_sets_both_secrets():
    setup = build_setup_sh([SecretProvider.ZOHO_MAIL])
    assert (
        f"printf '%s' \"$AAI_SECRET_ZOHO_CLIENT_SECRET\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set zoho.client_secret" in setup
    )
    assert (
        f"printf '%s' \"$AAI_SECRET_ZOHO_MAIL_REFRESH_TOKEN\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set zoho.mail_refresh_token" in setup
    )


def test_setup_sh_no_store_providers_only_copies():
    setup = build_setup_sh([])
    assert f"cp /app/config/aai-cli-config.toml {CONFIG_PATH}" in setup
    assert "secrets set" not in setup


def test_build_env_maps_tokens_to_env_vars():
    env = build_env({SecretProvider.JIRA: _JIRA, SecretProvider.GITHUB: _GITHUB})
    assert env == {
        "AAI_SECRET_JIRA_API_TOKEN": "jira_tok",
        "AAI_SECRET_GITHUB_TOKEN": "ghp_tok",
    }


def test_build_env_gmail_emits_both_secrets():
    env = build_env({SecretProvider.GMAIL: _GMAIL})
    assert env == {
        "AAI_SECRET_GOOGLE_CLIENT_SECRET": "g_client_secret",
        "AAI_SECRET_GOOGLE_GMAIL_REFRESH_TOKEN": "g_refresh_tok",
    }


def test_build_env_zoho_mail_emits_both_secrets():
    env = build_env({SecretProvider.ZOHO_MAIL: _ZOHO_MAIL})
    assert env == {
        "AAI_SECRET_ZOHO_CLIENT_SECRET": "z_client_secret",
        "AAI_SECRET_ZOHO_MAIL_REFRESH_TOKEN": "z_refresh_tok",
    }


def test_build_env_ignores_non_store_providers():
    # GOOGLE_CALENDAR uses token_env, not the secret store
    assert build_env({SecretProvider.GOOGLE_CALENDAR: _GOOGLE_CALENDAR}) == {}


def test_config_toml_hermes_home_dir_uses_opt_data_paths():
    toml = build_config_toml({SecretProvider.JIRA: _JIRA}, home_dir="/opt/data")
    assert 'secrets_file = "/opt/data/.config/aai-cli/aai-secrets.enc.json"' in toml
    assert 'key_file = "/opt/data/.config/aai-cli/key"' in toml
    assert "/home/node" not in toml


def test_config_toml_default_home_dir_is_home_node():
    toml = build_config_toml({SecretProvider.JIRA: _JIRA})
    assert "/home/node/.config/aai-cli" in toml


def test_setup_sh_hermes_home_dir_exports_opt_data():
    setup = build_setup_sh([SecretProvider.JIRA], home_dir="/opt/data")
    assert "export HOME=/opt/data" in setup
    assert "mkdir -p /opt/data/.config/aai-cli" in setup
    assert (
        "cp /app/config/aai-cli-config.toml /opt/data/.config/aai-cli/config.toml"
        in setup
    )
    assert "/home/node" not in setup


def test_setup_sh_default_home_dir_is_home_node():
    setup = build_setup_sh([])
    assert "export HOME=/home/node" in setup
