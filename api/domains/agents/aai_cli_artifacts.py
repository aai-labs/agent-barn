"""Builders for the aai-cli tool's runtime artifacts (config.toml, setup script, env).

These are pure string/dict builders (no k8s types) consumed by ``start_agent`` to inject an
agent's integration secrets into its pod so the baked-in ``aai-cli`` can use them.
"""

from collections.abc import Callable
from typing import Mapping

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
    GmailContent,
    GoogleCalendarContent,
    JiraContent,
    SecretContent,
    SecretProvider,
    ZohoCalendarContent,
    ZohoMailContent,
)

# Maps each provider to its (secret_name, content_attr) pairs for the aai-cli encrypted
# secret store. Each tuple: (secret_name referenced in config.toml, attr on the content model).
# Providers not listed here don't use the store (env-based only, e.g. google-calendar).
provider_secrets_map: dict[str, list[tuple[str, str]]] = {
    "github": [("github.token", "token")],
    "jira": [("jira.api_token", "api_token")],
    "confluence": [("confluence.api_token", "api_token")],
    "bitbucket": [("bitbucket.api_token", "api_token")],
    "gmail": [
        ("google.client_secret", "client_secret"),
        ("google.gmail_refresh_token", "refresh_token"),
    ],
    "zoho_mail": [
        ("zoho.client_secret", "client_secret"),
        ("zoho.mail_refresh_token", "refresh_token"),
    ],
}

# Default config dir for OpenClaw (node user). Callers can pass a different home_dir for other
# runtimes (e.g. Hermes runs as root → home_dir="/root").
SECRETS_DIR = "/home/node/.config/aai-cli"
CONFIG_PATH = f"{SECRETS_DIR}/config.toml"


def _header(secrets_dir: str) -> str:
    return (
        f'secrets_file = "{secrets_dir}/aai-secrets.enc.json"\n'
        f'key_file = "{secrets_dir}/key"\n'
    )


def env_var_for(secret_name: str) -> str:
    """ "jira.api_token" -> "AAI_SECRET_JIRA_API_TOKEN"."""
    return "AAI_SECRET_" + secret_name.upper().replace(".", "_")


def _q(value: str) -> str:
    """TOML-quote a string value, escaping backslashes and double quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --- per-provider profile blocks (rendered from the decrypted content model) ---


def _github_block(c: GithubContent) -> str:
    return (
        "[profiles.github-work]\n"
        'provider = "github"\n'
        'auth_type = "bearer_token"\n'
        'token_secret = "github.token"\n'
        f"owner = {_q(c.owner)}\n"
        f"repo = {_q(c.repo)}\n"
        f"org = {_q(c.org)}\n"
    )


def _jira_block(c: JiraContent) -> str:
    return (
        "[profiles.jira-work]\n"
        'auth_type = "basic_api_token"\n'
        f"site_url = {_q(c.site_url)}\n"
        f"email = {_q(c.email)}\n"
        'api_token_secret = "jira.api_token"\n'
    )


def _confluence_block(c: ConfluenceContent) -> str:
    return (
        "[profiles.confluence-work]\n"
        'auth_type = "basic_api_token"\n'
        f"site_url = {_q(c.site_url)}\n"
        f"email = {_q(c.email)}\n"
        'api_token_secret = "confluence.api_token"\n'
    )


def _bitbucket_block(c: BitbucketContent) -> str:
    return (
        "[profiles.bitbucket-work]\n"
        'auth_type = "basic_api_token"\n'
        f"workspace = {_q(c.workspace)}\n"
        f"repo = {_q(c.repo)}\n"
        f"email = {_q(c.email)}\n"
        'api_token_secret = "bitbucket.api_token"\n'
    )


def _gmail_block(c: GmailContent) -> str:
    return (
        "[profiles.gmail-work]\n"
        'provider = "google"\n'
        'auth_type = "bearer_token"\n'
        f"client_id = {_q(c.client_id)}\n"
        'client_secret_secret = "google.client_secret"\n'
        'refresh_token_secret = "google.gmail_refresh_token"\n'
        'user_id = "me"\n'
    )


def _google_calendar_block(c: GoogleCalendarContent) -> str:
    return (
        "[profiles.google-calendar-work]\n"
        'provider = "google"\n'
        'auth_type = "bearer_token"\n'
        'token_env = "GOOGLE_CALENDAR_ACCESS_TOKEN"\n'
        f"calendar_id = {_q(c.calendar_id)}\n"
    )


def _zoho_mail_block(c: ZohoMailContent) -> str:
    return (
        "[profiles.zoho-mail-rest]\n"
        'provider = "zoho"\n'
        'auth_type = "zoho_oauth"\n'
        f"email = {_q(c.email)}\n"
        f"account_id = {_q(c.account_id)}\n"
        f"client_id = {_q(c.client_id)}\n"
        'client_secret_secret = "zoho.client_secret"\n'
        'refresh_token_secret = "zoho.mail_refresh_token"\n'
    )


def _zoho_calendar_block(c: ZohoCalendarContent) -> str:
    return (
        "[profiles.zoho-calendar-work]\n"
        'provider = "zoho"\n'
        'transport = "caldav"\n'
        'auth_type = "app_password"\n'
        f"username = {_q(c.username)}\n"
        f"email = {_q(c.email)}\n"
        'password_env = "ZOHO_CALENDAR_APP_PASSWORD"\n'
        f"caldav_url = {_q(c.caldav_url)}\n"
    )


_PROFILE_BUILDERS: dict[SecretProvider, Callable[..., str]] = {
    SecretProvider.GITHUB: _github_block,
    SecretProvider.JIRA: _jira_block,
    SecretProvider.CONFLUENCE: _confluence_block,
    SecretProvider.BITBUCKET: _bitbucket_block,
    SecretProvider.GMAIL: _gmail_block,
    SecretProvider.GOOGLE_CALENDAR: _google_calendar_block,
    SecretProvider.ZOHO_MAIL: _zoho_mail_block,
    SecretProvider.ZOHO_CALENDAR: _zoho_calendar_block,
}


def build_tool_context_md(decrypted: Mapping[SecretProvider, SecretContent]) -> str:
    """Render a markdown section listing each configured integration's key metadata.

    Injected into tools_md at start_agent time so the agent knows what is already
    set up and doesn't ask the user for credentials that are already configured.
    """
    if not decrypted:
        return ""

    lines: list[str] = [
        "\n## Configured Integrations\n",
        "The following integrations are pre-configured via aai-cli. "
        "Use aai-cli to interact with them — credentials are already in place. "
        "Do not ask the user to re-provide them.\n",
    ]
    for provider in SecretProvider:
        content = decrypted.get(provider)
        if content is None:
            continue
        if isinstance(content, GithubContent):
            lines.append(
                f"- **GitHub** (`github-work`): {content.owner}/{content.repo}"
            )
        elif isinstance(content, JiraContent):
            lines.append(
                f"- **Jira** (`jira-work`): {content.site_url} ({content.email})"
            )
        elif isinstance(content, ConfluenceContent):
            lines.append(
                f"- **Confluence** (`confluence-work`): {content.site_url} ({content.email})"
            )
        elif isinstance(content, BitbucketContent):
            lines.append(
                f"- **Bitbucket** (`bitbucket-work`): {content.workspace}/{content.repo} ({content.email})"
            )
    return "\n".join(lines) + "\n"


def build_config_toml(
    decrypted: Mapping[SecretProvider, SecretContent],
    home_dir: str = "/home/node",
) -> str:
    """Render config.toml with one profile per provider present in ``decrypted``.

    Providers are emitted in a fixed (enum) order for deterministic output. Store-based providers
    reference their secret via ``*_secret``; env-based providers via ``*_env`` (token not injected).
    """
    secrets_dir = f"{home_dir}/.config/aai-cli"
    blocks = [_header(secrets_dir)]
    for provider in SecretProvider:
        content = decrypted.get(provider)
        if content is not None:
            blocks.append(_PROFILE_BUILDERS[provider](content))
    return "\n".join(blocks)


def build_setup_sh(
    store_providers: list[SecretProvider],
    home_dir: str = "/home/node",
) -> str:
    """Render the in-pod setup script: install config.toml, then `secrets set` per store secret.

    The ``cp`` always runs (installs the mounted config); `secrets set` lines are emitted only for
    store-based providers (``store_providers``), one line per secret name.
    """
    secrets_dir = f"{home_dir}/.config/aai-cli"
    config_path = f"{secrets_dir}/config.toml"
    present = set(store_providers)
    lines = [
        "#!/bin/sh",
        "set -e",
        f"export HOME={home_dir}",
        f"mkdir -p {secrets_dir}",
        f"cp /app/config/aai-cli-config.toml {config_path}",
    ]
    for provider in SecretProvider:  # fixed order for determinism
        if provider not in present:
            continue
        for secret_name, _ in provider_secrets_map.get(provider.value, []):
            env = env_var_for(secret_name)
            lines.append(
                f"printf '%s' \"${env}\" | "
                f"aai-cli --config {config_path} secrets set {secret_name}"
            )
    return "\n".join(lines) + "\n"


def build_env(
    store_decrypted: Mapping[SecretProvider, SecretContent],
) -> dict[str, str]:
    """Env vars (AAI_SECRET_*) carrying the decrypted token for each store-based provider.

    Non-store providers are ignored, so a mixed mapping can be passed safely.
    """
    env: dict[str, str] = {}
    for provider, content in store_decrypted.items():
        for secret_name, attr in provider_secrets_map.get(provider.value, []):
            env[env_var_for(secret_name)] = getattr(content, attr)
    return env
