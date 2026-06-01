from api.domains.agents.aai_cli_artifacts import (
    CONFIG_PATH,
    build_config_toml,
    build_env,
    build_setup_sh,
    env_var_for,
    token_attr,
)
from api.domains.agents.models import SecretProvider, validate_content

_GITHUB = validate_content(
    SecretProvider.GITHUB,
    {"token": "ghp_tok", "owner": "aai-labs", "repo": "agent-farm", "org": "aai-labs"},
)
_JIRA = validate_content(
    SecretProvider.JIRA,
    {"site_url": "https://x.atlassian.net", "email": "a@b.com", "api_token": "jira_tok"},
)
_CONFLUENCE = validate_content(
    SecretProvider.CONFLUENCE,
    {"site_url": "https://x.atlassian.net", "email": "a@b.com", "api_token": "conf_tok"},
)
_GMAIL = validate_content(
    SecretProvider.GMAIL, {"access_token": "g_tok", "user_id": "me"}
)


def test_helpers():
    assert env_var_for("jira.api_token") == "AAI_SECRET_JIRA_API_TOKEN"
    assert env_var_for("github.token") == "AAI_SECRET_GITHUB_TOKEN"
    assert token_attr("github.token") == "token"
    assert token_attr("jira.api_token") == "api_token"


def test_config_toml_emits_only_present_store_profiles():
    toml = build_config_toml(
        {
            SecretProvider.JIRA: _JIRA,
            SecretProvider.CONFLUENCE: _CONFLUENCE,
            SecretProvider.GITHUB: _GITHUB,
        }
    )
    # header with absolute paths
    assert 'secrets_file = "/home/node/.config/aai-cli/aai-secrets.enc.json"' in toml
    assert 'key_file = "/home/node/.config/aai-cli/key"' in toml
    # exactly the three present profiles
    assert "[profiles.jira-work]" in toml
    assert "[profiles.confluence-work]" in toml
    assert "[profiles.github-work]" in toml
    assert "[profiles.bitbucket-work]" not in toml
    assert "[profiles.gmail-work]" not in toml
    # store-based providers reference the encrypted store, real DB values rendered
    assert 'api_token_secret = "jira.api_token"' in toml
    assert 'token_secret = "github.token"' in toml
    assert 'site_url = "https://x.atlassian.net"' in toml
    assert 'owner = "aai-labs"' in toml
    # token VALUES never appear in the config (they go via env / secret store)
    assert "jira_tok" not in toml
    assert "ghp_tok" not in toml


def test_config_toml_env_based_provider_uses_env_no_secret():
    toml = build_config_toml({SecretProvider.GMAIL: _GMAIL})
    assert "[profiles.gmail-work]" in toml
    assert 'token_env = "GOOGLE_GMAIL_ACCESS_TOKEN"' in toml
    assert "secret" not in toml.split("[profiles.gmail-work]")[1]  # no *_secret for gmail


def test_setup_sh_cp_always_and_secrets_set_per_store_provider():
    setup = build_setup_sh([SecretProvider.JIRA, SecretProvider.GITHUB])
    assert f"cp /app/config/aai-cli-config.toml {CONFIG_PATH}" in setup
    assert (
        f'printf \'%s\' "$AAI_SECRET_JIRA_API_TOKEN" | '
        f"aai-cli --config {CONFIG_PATH} secrets set jira.api_token" in setup
    )
    assert "secrets set github.token" in setup
    # no raw token values in the script
    assert "jira_tok" not in setup


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


def test_build_env_ignores_non_store_providers():
    assert build_env({SecretProvider.GMAIL: _GMAIL}) == {}
