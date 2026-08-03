from typing import cast

from api.domains.agents.aai_cli_artifacts import (
    CONFIG_PATH,
    PROFILE_SLUGS,
    build_config_toml,
    build_env,
    build_integrations_policy_md,
    build_setup_sh,
    build_tool_context_md,
    env_var_for,
)
from api.domains.agents.models import (
    FirecrawlContent,
    GmailContent,
    PipedriveContent,
    SecretProvider,
    ZohoMailContent,
    validate_content,
)

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
_BITBUCKET = validate_content(
    SecretProvider.BITBUCKET,
    {
        "workspace": "my-workspace",
        "repo": "my-repo",
        "email": "a@b.com",
        "api_token": "bb_tok",
    },
)
_GMAIL = cast(
    GmailContent,
    validate_content(
        SecretProvider.GMAIL,
        {
            "client_id": "132806748841-abc.apps.googleusercontent.com",
            "client_secret": "g_client_secret",
            "refresh_token": "g_refresh_tok",
        },
    ),
)
_ZOHO_MAIL = cast(
    ZohoMailContent,
    validate_content(
        SecretProvider.ZOHO_MAIL,
        {
            "email": "samuel@aai-labs.com",
            "account_id": "56218000000008002",
            "client_id": "1000.WNPJ721D9UHU9SIHFSU4WA2P04W9LI",
            "client_secret": "z_client_secret",
            "refresh_token": "z_refresh_tok",
        },
    ),
)
_GOOGLE_CALENDAR = validate_content(
    SecretProvider.GOOGLE_CALENDAR,
    {"access_token": "gc_tok", "calendar_id": "primary"},
)
_PIPEDRIVE = cast(
    PipedriveContent,
    validate_content(SecretProvider.PIPEDRIVE, {"api_token": "pd_tok"}),
)
_PIPEDRIVE_WITH_DOMAIN = cast(
    PipedriveContent,
    validate_content(SecretProvider.PIPEDRIVE, {"api_token": "pd_tok", "domain": "aai-labs"}),
)


def test_env_var_for():
    assert env_var_for("jira.api_token") == "AAI_SECRET_JIRA_API_TOKEN"
    assert env_var_for("github.token") == "AAI_SECRET_GITHUB_TOKEN"
    assert env_var_for("google.client_secret") == "AAI_SECRET_GOOGLE_CLIENT_SECRET"
    assert env_var_for("google.gmail_refresh_token") == "AAI_SECRET_GOOGLE_GMAIL_REFRESH_TOKEN"
    assert env_var_for("zoho.client_secret") == "AAI_SECRET_ZOHO_CLIENT_SECRET"
    assert env_var_for("zoho.mail_refresh_token") == "AAI_SECRET_ZOHO_MAIL_REFRESH_TOKEN"
    assert env_var_for("pipedrive.api_token") == "AAI_SECRET_PIPEDRIVE_API_TOKEN"


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


def test_config_toml_jira_scoped_token_uses_gateway_url():
    jira_scoped = validate_content(
        SecretProvider.JIRA,
        {
            "site_url": "https://x.atlassian.net",
            "email": "svc-account@x.com",
            "api_token": "jira_scoped_tok",
            "use_scoped_token": True,
            "cloud_id": "cloud-abc",
        },
    )
    toml = build_config_toml({SecretProvider.JIRA: jira_scoped})
    assert "[profiles.jira-work]" in toml
    assert 'auth_type = "basic_api_token"' in toml
    assert 'site_url = "https://api.atlassian.com/ex/jira/cloud-abc"' in toml
    assert 'email = "svc-account@x.com"' in toml


def test_config_toml_jira_scoped_token_missing_cloud_id_skips_profile():
    jira_scoped_no_cloud_id = validate_content(
        SecretProvider.JIRA,
        {
            "site_url": "https://x.atlassian.net",
            "email": "svc-account@x.com",
            "api_token": "jira_scoped_tok",
            "use_scoped_token": True,
        },
    )
    toml = build_config_toml({SecretProvider.JIRA: jira_scoped_no_cloud_id})
    assert "[profiles.jira-work]" not in toml
    assert "cloud_id missing" in toml


def test_config_toml_confluence_scoped_token_uses_gateway_url():
    confluence_scoped = validate_content(
        SecretProvider.CONFLUENCE,
        {
            "site_url": "https://x.atlassian.net",
            "email": "svc-account@x.com",
            "api_token": "conf_scoped_tok",
            "use_scoped_token": True,
            "cloud_id": "cloud-abc",
        },
    )
    toml = build_config_toml({SecretProvider.CONFLUENCE: confluence_scoped})
    assert "[profiles.confluence-work]" in toml
    assert 'auth_type = "basic_api_token"' in toml
    assert 'site_url = "https://api.atlassian.com/ex/confluence/cloud-abc"' in toml
    assert 'email = "svc-account@x.com"' in toml


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


def test_config_toml_pipedrive_without_domain_omits_base_url():
    toml = build_config_toml({SecretProvider.PIPEDRIVE: _PIPEDRIVE})
    assert "[profiles.pipedrive-work]" in toml
    assert 'auth_type = "pipedrive_personal_token"' in toml
    assert 'api_token_secret = "pipedrive.api_token"' in toml
    assert "base_url" not in toml
    assert "pd_tok" not in toml


def test_config_toml_pipedrive_with_domain_emits_base_url():
    toml = build_config_toml({SecretProvider.PIPEDRIVE: _PIPEDRIVE_WITH_DOMAIN})
    assert "[profiles.pipedrive-work]" in toml
    assert 'base_url = "https://aai-labs.pipedrive.com"' in toml


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


def test_setup_sh_pipedrive_sets_secret():
    setup = build_setup_sh([SecretProvider.PIPEDRIVE])
    assert (
        f"printf '%s' \"$AAI_SECRET_PIPEDRIVE_API_TOKEN\" | "
        f"aai-cli --config {CONFIG_PATH} secrets set pipedrive.api_token" in setup
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


def test_build_env_pipedrive_emits_secret():
    env = build_env({SecretProvider.PIPEDRIVE: _PIPEDRIVE})
    assert env == {"AAI_SECRET_PIPEDRIVE_API_TOKEN": "pd_tok"}


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
    assert "cp /app/config/aai-cli-config.toml /opt/data/.config/aai-cli/config.toml" in setup
    assert "/home/node" not in setup


def test_setup_sh_default_home_dir_is_home_node():
    setup = build_setup_sh([])
    assert "export HOME=/home/node" in setup


# --- build_tool_context_md ----------------------------------------------------


def test_tool_context_md_empty_when_no_secrets():
    assert build_tool_context_md({}) == ""


def test_tool_context_md_lists_github_profile():
    md = build_tool_context_md({SecretProvider.GITHUB: _GITHUB})
    assert "github-work" in md
    assert "aai-labs/agent-farm" in md
    assert "Do not ask the user to re-provide" in md


def test_tool_context_md_lists_jira_profile():
    md = build_tool_context_md({SecretProvider.JIRA: _JIRA})
    assert "jira-work" in md
    assert "https://x.atlassian.net" in md
    assert "a@b.com" in md


def test_tool_context_md_lists_confluence_profile():
    md = build_tool_context_md({SecretProvider.CONFLUENCE: _CONFLUENCE})
    assert "confluence-work" in md
    assert "https://x.atlassian.net" in md


def test_tool_context_md_lists_bitbucket_profile():
    md = build_tool_context_md({SecretProvider.BITBUCKET: _BITBUCKET})
    assert "bitbucket-work" in md
    assert "my-workspace/my-repo" in md


def test_tool_context_md_omits_non_aai_cli_providers():
    md = build_tool_context_md({SecretProvider.GMAIL: _GMAIL})
    assert md == ""


def test_tool_context_md_empty_when_only_firecrawl():
    md = build_tool_context_md({SecretProvider.FIRECRAWL: FirecrawlContent(api_key="fc-x")})
    assert md == ""


def test_tool_context_md_empty_when_only_pipedrive():
    # Pipedrive is deliberately excluded from _TOOL_CONTEXT_PROVIDERS — no per-secret
    # metadata (site URL, owner/workspace) worth surfacing beyond "configured".
    md = build_tool_context_md({SecretProvider.PIPEDRIVE: _PIPEDRIVE})
    assert md == ""


def test_tool_context_md_never_leaks_tokens():
    md = build_tool_context_md(
        {
            SecretProvider.GITHUB: _GITHUB,
            SecretProvider.JIRA: _JIRA,
            SecretProvider.BITBUCKET: _BITBUCKET,
        }
    )
    assert "ghp_tok" not in md
    assert "jira_tok" not in md
    assert "bb_tok" not in md


def test_tool_context_md_lists_multiple_providers():
    md = build_tool_context_md(
        {
            SecretProvider.GITHUB: _GITHUB,
            SecretProvider.JIRA: _JIRA,
            SecretProvider.CONFLUENCE: _CONFLUENCE,
        }
    )
    assert "github-work" in md
    assert "jira-work" in md
    assert "confluence-work" in md


# --- build_integrations_policy_md ---------------------------------------------


def test_integrations_policy_md_empty_when_no_secrets():
    assert build_integrations_policy_md({}) == ""


def test_integrations_policy_md_includes_no_fallback_policy():
    md = build_integrations_policy_md({SecretProvider.JIRA: _JIRA})
    # aai-cli is the only path; always pass --profile; no browser/curl/HTTP fallback;
    # don't invent URLs/tokens; pointer to the on-demand skill docs.
    assert "aai-cli" in md
    assert "--profile" in md
    assert "curl" in md
    assert "./skills/aai-cli/" in md


def test_integrations_policy_md_includes_nested_command_grammar():
    # Agents burn turns guessing subcommands (they try `... get AF-147` at the top
    # level); the block must show the 3-level grammar, a worked example, and steer
    # them to read the skill file rather than look it up by name.
    md = build_integrations_policy_md({SecretProvider.JIRA: _JIRA})
    assert "aai-cli --profile <slug> <service> <resource> <verb>" in md
    assert "aai-cli --profile jira-work jira issues get AF-147" in md
    assert "./skills/aai-cli/<service>_skill.md" in md


def test_integrations_policy_md_emits_profile_line_per_provider():
    md = build_integrations_policy_md({SecretProvider.JIRA: _JIRA})
    assert "--profile jira-work" in md


def test_integrations_policy_md_github_multi_repo_lists_all_profiles():
    github = validate_content(
        SecretProvider.GITHUB,
        {
            "token": "ghp_tok",
            "owner": "aai-labs",
            "repos": ["agent-farm", "ocbw"],
            "org": "aai-labs",
        },
    )
    md = build_integrations_policy_md({SecretProvider.GITHUB: github})
    assert "--profile github-work" in md
    assert "--profile github-work-2" in md


def test_integrations_policy_md_github_multi_repo_maps_each_slug_to_its_repo():
    # An agent with several repos can't act on a bare slug list — each --profile
    # must name the owner/repo it targets so the agent picks the right one.
    github = validate_content(
        SecretProvider.GITHUB,
        {
            "token": "ghp_tok",
            "owner": "aai-labs",
            "repos": ["agent-farm", "ocbw"],
            "org": "aai-labs",
        },
    )
    md = build_integrations_policy_md({SecretProvider.GITHUB: github})
    assert "`--profile github-work` → aai-labs/agent-farm" in md
    assert "`--profile github-work-2` → aai-labs/ocbw" in md


def test_integrations_policy_md_github_no_repo_guides_repo_flag():
    # No repo is baked into the profile, so the profile has no `repo =` line and
    # aai-cli requires `--repo`; the block must tell the agent to pass it.
    # A non-aai-labs owner, asserted verbatim: the owner is taken from the configured
    # secret (content.owner), never hardcoded, so this works for any org.
    github = validate_content(
        SecretProvider.GITHUB,
        {"token": "ghp_tok", "owner": "octo-org", "org": "octo-org"},
    )
    md = build_integrations_policy_md({SecretProvider.GITHUB: github})
    assert "--profile github-work" in md
    assert "owner `octo-org`" in md
    assert "aai-labs" not in md
    assert "no repo configured" in md
    assert "--repo" in md


def test_integrations_policy_md_bitbucket_multi_repo_maps_each_slug_to_its_repo():
    # Same guarantee as GitHub, for Bitbucket's workspace/repo scoping.
    bitbucket = validate_content(
        SecretProvider.BITBUCKET,
        {
            "workspace": "my-workspace",
            "repos": ["repo-a", "repo-b"],
            "email": "a@b.com",
            "api_token": "bb_tok",
        },
    )
    md = build_integrations_policy_md({SecretProvider.BITBUCKET: bitbucket})
    assert "`--profile bitbucket-work` → my-workspace/repo-a" in md
    assert "`--profile bitbucket-work-2` → my-workspace/repo-b" in md


def test_integrations_policy_md_bitbucket_no_repo_guides_repo_flag():
    bitbucket = validate_content(
        SecretProvider.BITBUCKET,
        {"workspace": "my-workspace", "email": "a@b.com", "api_token": "bb_tok"},
    )
    md = build_integrations_policy_md({SecretProvider.BITBUCKET: bitbucket})
    assert "--profile bitbucket-work" in md
    assert "no repo configured" in md
    assert "--repo" in md


def test_integrations_policy_md_covers_non_store_providers():
    md = build_integrations_policy_md(
        {
            SecretProvider.GMAIL: _GMAIL,
            SecretProvider.ZOHO_MAIL: _ZOHO_MAIL,
        }
    )
    assert "--profile gmail-work" in md
    assert "--profile zoho-mail-rest" in md


def test_integrations_policy_md_pipedrive_emits_profile_line():
    md = build_integrations_policy_md({SecretProvider.PIPEDRIVE: _PIPEDRIVE})
    assert "--profile pipedrive-work" in md
    assert "pd_tok" not in md


def test_profile_slugs_are_single_source_of_truth_for_jira():
    # The config.toml profile header and the agents_md --profile line must both derive
    # from PROFILE_SLUGS, so they can never drift apart.
    slug = PROFILE_SLUGS[SecretProvider.JIRA]
    assert f"[profiles.{slug}]" in build_config_toml({SecretProvider.JIRA: _JIRA})
    assert f"--profile {slug}" in build_integrations_policy_md({SecretProvider.JIRA: _JIRA})


def test_integrations_policy_md_never_leaks_tokens():
    md = build_integrations_policy_md(
        {
            SecretProvider.GITHUB: _GITHUB,
            SecretProvider.JIRA: _JIRA,
            SecretProvider.GMAIL: _GMAIL,
        }
    )
    assert "ghp_tok" not in md
    assert "jira_tok" not in md
    assert "g_client_secret" not in md
    assert "g_refresh_tok" not in md
