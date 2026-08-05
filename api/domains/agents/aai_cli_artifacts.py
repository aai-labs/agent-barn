"""Builders for the aai-cli tool's runtime artifacts (config.toml, setup script, env).

These are pure string/dict builders (no k8s types) consumed by ``start_agent`` to inject an
agent's integration secrets into its pod so the baked-in ``aai-cli`` can use them.
"""

from collections.abc import Callable, Mapping

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
    GmailContent,
    GoogleCalendarContent,
    GoogleSheetsContent,
    JiraContent,
    PipedriveContent,
    SecretContent,
    SecretProvider,
    SlackContent,
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
    # Deliberately not sharing gmail's "google.client_secret": a user may bring their own
    # Google client for one provider and use the app-owned one for the other, and these
    # names are flat keys in the same store — sharing would let one clobber the other.
    "google_sheets": [
        ("google.sheets_client_secret", "client_secret"),
        ("google.sheets_refresh_token", "refresh_token"),
    ],
    "zoho_mail": [
        ("zoho.client_secret", "client_secret"),
        ("zoho.mail_refresh_token", "refresh_token"),
    ],
    "slack": [("slack.token", "token")],
    "pipedrive": [("pipedrive.api_token", "api_token")],
}

# Canonical aai-cli --profile slug per provider — the single source of truth shared by the
# config.toml profile builders (which emit `[profiles.<slug>]`) and the markdown that tells
# the agent which --profile to pass. GitHub/Bitbucket use this as the base slug; each extra
# configured repo appends -2, -3, ... via _profile_repo_pairs.
PROFILE_SLUGS: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "github-work",
    SecretProvider.JIRA: "jira-work",
    SecretProvider.CONFLUENCE: "confluence-work",
    SecretProvider.BITBUCKET: "bitbucket-work",
    SecretProvider.GMAIL: "gmail-work",
    SecretProvider.GOOGLE_CALENDAR: "google-calendar-work",
    SecretProvider.GOOGLE_SHEETS: "google-sheets-work",
    SecretProvider.ZOHO_MAIL: "zoho-mail-rest",
    SecretProvider.ZOHO_CALENDAR: "zoho-calendar-work",
    SecretProvider.SLACK: "slack-work",
    SecretProvider.PIPEDRIVE: "pipedrive-work",
}

# Default config dir for OpenClaw (node user). Callers can pass a different home_dir for other
# runtimes (e.g. Hermes runs as root → home_dir="/root").
SECRETS_DIR = "/home/node/.config/aai-cli"
CONFIG_PATH = f"{SECRETS_DIR}/config.toml"


def _header(secrets_dir: str) -> str:
    return f'secrets_file = "{secrets_dir}/aai-secrets.enc.json"\nkey_file = "{secrets_dir}/key"\n'


def env_var_for(secret_name: str) -> str:
    """ "jira.api_token" -> "AAI_SECRET_JIRA_API_TOKEN"."""
    return "AAI_SECRET_" + secret_name.upper().replace(".", "_")


def _q(value: str) -> str:
    """TOML-quote a string value, escaping backslashes and double quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _profile_repo_pairs(base_name: str, repos: list[str]) -> list[tuple[str, str | None]]:
    """Map a list of repo names to (profile_name, repo) pairs.

    [] -> [(base_name, None)] (profile with no `repo =` line — aai-cli falls back to
    a `--repo` CLI flag). [r1, r2, ...] -> [(base_name, r1), (f"{base_name}-2", r2), ...].
    """
    if not repos:
        return [(base_name, None)]
    return [(base_name if i == 0 else f"{base_name}-{i + 1}", repo) for i, repo in enumerate(repos)]


# --- per-provider profile blocks (rendered from the decrypted content model) ---


def _github_block(c: GithubContent) -> str:
    blocks = []
    for name, repo in _profile_repo_pairs(PROFILE_SLUGS[SecretProvider.GITHUB], c.repos):
        lines = [
            f"[profiles.{name}]\n",
            'provider = "github"\n',
            'auth_type = "bearer_token"\n',
            'token_secret = "github.token"\n',
            f"owner = {_q(c.owner)}\n",
        ]
        if repo is not None:
            lines.append(f"repo = {_q(repo)}\n")
        lines.append(f"org = {_q(c.org)}\n")
        blocks.append("".join(lines))
    return "\n".join(blocks)


def _jira_block(c: JiraContent) -> str:
    site_url = c.site_url
    if c.use_scoped_token:
        # Scoped tokens are still Basic Auth, but must go through the API Gateway
        # (keyed by cloud_id) rather than the site URL directly.
        # If cloud_id is missing, skip the profile — the user must re-save the integration.
        if not c.cloud_id:
            return "# jira-work profile skipped: cloud_id missing\n"
        site_url = f"https://api.atlassian.com/ex/jira/{c.cloud_id}"
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.JIRA]}]\n"
        'auth_type = "basic_api_token"\n'
        f"site_url = {_q(site_url)}\n"
        f"email = {_q(c.email)}\n"
        'api_token_secret = "jira.api_token"\n'
    )


def _confluence_block(c: ConfluenceContent) -> str:
    site_url = c.site_url
    if c.use_scoped_token:
        # Scoped tokens are still Basic Auth, but must go through the API Gateway
        # (keyed by cloud_id) rather than the site URL directly.
        # If cloud_id is missing, skip the profile — the user must re-save the integration.
        if not c.cloud_id:
            return "# confluence-work profile skipped: cloud_id missing\n"
        site_url = f"https://api.atlassian.com/ex/confluence/{c.cloud_id}"
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.CONFLUENCE]}]\n"
        'auth_type = "basic_api_token"\n'
        f"site_url = {_q(site_url)}\n"
        f"email = {_q(c.email)}\n"
        'api_token_secret = "confluence.api_token"\n'
    )


def _bitbucket_block(c: BitbucketContent) -> str:
    blocks = []
    for name, repo in _profile_repo_pairs(PROFILE_SLUGS[SecretProvider.BITBUCKET], c.repos):
        lines = [
            f"[profiles.{name}]\n",
            'auth_type = "basic_api_token"\n',
            f"workspace = {_q(c.workspace)}\n",
        ]
        if repo is not None:
            lines.append(f"repo = {_q(repo)}\n")
        lines.append(f"email = {_q(c.email)}\n")
        lines.append('api_token_secret = "bitbucket.api_token"\n')
        blocks.append("".join(lines))
    return "\n".join(blocks)


def _gmail_block(c: GmailContent) -> str:
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.GMAIL]}]\n"
        'provider = "google"\n'
        'auth_type = "bearer_token"\n'
        f"client_id = {_q(c.client_id)}\n"
        'client_secret_secret = "google.client_secret"\n'
        'refresh_token_secret = "google.gmail_refresh_token"\n'
        'user_id = "me"\n'
    )


def _google_sheets_block(c: GoogleSheetsContent) -> str:
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.GOOGLE_SHEETS]}]\n"
        'provider = "google"\n'
        'auth_type = "bearer_token"\n'
        f"client_id = {_q(c.client_id)}\n"
        'client_secret_secret = "google.sheets_client_secret"\n'
        'refresh_token_secret = "google.sheets_refresh_token"\n'
    )


def _google_calendar_block(c: GoogleCalendarContent) -> str:
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.GOOGLE_CALENDAR]}]\n"
        'provider = "google"\n'
        'auth_type = "bearer_token"\n'
        'token_env = "GOOGLE_CALENDAR_ACCESS_TOKEN"\n'
        f"calendar_id = {_q(c.calendar_id)}\n"
    )


def _zoho_mail_block(c: ZohoMailContent) -> str:
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.ZOHO_MAIL]}]\n"
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
        f"[profiles.{PROFILE_SLUGS[SecretProvider.ZOHO_CALENDAR]}]\n"
        'provider = "zoho"\n'
        'transport = "caldav"\n'
        'auth_type = "app_password"\n'
        f"username = {_q(c.username)}\n"
        f"email = {_q(c.email)}\n"
        'password_env = "ZOHO_CALENDAR_APP_PASSWORD"\n'
        f"caldav_url = {_q(c.caldav_url)}\n"
    )


def _slack_block(c: SlackContent) -> str:
    return (
        f"[profiles.{PROFILE_SLUGS[SecretProvider.SLACK]}]\n"
        'provider = "slack"\n'
        'auth_type = "bearer_token"\n'
        'token_secret = "slack.token"\n'
    )


def _pipedrive_block(c: PipedriveContent) -> str:
    lines = [
        f"[profiles.{PROFILE_SLUGS[SecretProvider.PIPEDRIVE]}]\n",
        'auth_type = "pipedrive_personal_token"\n',
    ]
    if c.domain:
        lines.append(f"base_url = {_q(f'https://{c.domain}.pipedrive.com')}\n")
    lines.append('api_token_secret = "pipedrive.api_token"\n')
    return "".join(lines)


_PROFILE_BUILDERS: dict[SecretProvider, Callable[..., str]] = {
    SecretProvider.GITHUB: _github_block,
    SecretProvider.JIRA: _jira_block,
    SecretProvider.CONFLUENCE: _confluence_block,
    SecretProvider.BITBUCKET: _bitbucket_block,
    SecretProvider.GMAIL: _gmail_block,
    SecretProvider.GOOGLE_SHEETS: _google_sheets_block,
    SecretProvider.GOOGLE_CALENDAR: _google_calendar_block,
    SecretProvider.ZOHO_MAIL: _zoho_mail_block,
    SecretProvider.ZOHO_CALENDAR: _zoho_calendar_block,
    SecretProvider.SLACK: _slack_block,
    SecretProvider.PIPEDRIVE: _pipedrive_block,
}


_TOOL_CONTEXT_PROVIDERS = {
    SecretProvider.GITHUB,
    SecretProvider.JIRA,
    SecretProvider.CONFLUENCE,
    SecretProvider.BITBUCKET,
}


def build_tool_context_md(decrypted: Mapping[SecretProvider, SecretContent]) -> str:
    """Render a markdown section listing each configured integration's key metadata.

    Injected into tools_md at start_agent time so the agent knows what is already
    set up and doesn't ask the user for credentials that are already configured.
    """
    if not decrypted or not (decrypted.keys() & _TOOL_CONTEXT_PROVIDERS):
        return ""

    lines: list[str] = [
        "\n## Configured Integrations\n",
        (
            "The following integrations are pre-configured via aai-cli. "
            "Use aai-cli to interact with them — credentials are already in place. "
            "Do not ask the user to re-provide them.\n"
        ),
    ]
    for provider in SecretProvider:
        content = decrypted.get(provider)
        if content is None:
            continue
        if isinstance(content, GithubContent):
            base = PROFILE_SLUGS[SecretProvider.GITHUB]
            if content.repos:
                pairs = "; ".join(
                    f"`{name}`: {content.owner}/{repo}" for name, repo in _profile_repo_pairs(base, content.repos)
                )
                lines.append(f"- **GitHub**: {pairs}")
            else:
                lines.append(
                    f"- **GitHub** (`{base}`): owner/org `{content.owner}` — "
                    "no repository configured; pass --repo explicitly"
                )
        elif isinstance(content, JiraContent):
            slug = PROFILE_SLUGS[SecretProvider.JIRA]
            lines.append(f"- **Jira** (`{slug}`): {content.site_url} ({content.email})")
        elif isinstance(content, ConfluenceContent):
            slug = PROFILE_SLUGS[SecretProvider.CONFLUENCE]
            lines.append(f"- **Confluence** (`{slug}`): {content.site_url} ({content.email})")
        elif isinstance(content, BitbucketContent):
            base = PROFILE_SLUGS[SecretProvider.BITBUCKET]
            if content.repos:
                pairs = "; ".join(
                    f"`{name}`: {content.workspace}/{repo}" for name, repo in _profile_repo_pairs(base, content.repos)
                )
                lines.append(f"- **Bitbucket**: {pairs} ({content.email})")
            else:
                lines.append(
                    f"- **Bitbucket** (`{base}`): workspace `{content.workspace}` "
                    f"({content.email}) — no repository configured; pass --repo explicitly"
                )
    return "\n".join(lines) + "\n"


# Display label per provider for the agents_md integrations block.
_INTEGRATION_LABELS: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "GitHub",
    SecretProvider.JIRA: "Jira",
    SecretProvider.CONFLUENCE: "Confluence",
    SecretProvider.BITBUCKET: "Bitbucket",
    SecretProvider.GMAIL: "Gmail",
    SecretProvider.GOOGLE_CALENDAR: "Google Calendar",
    SecretProvider.GOOGLE_SHEETS: "Google Sheets",
    SecretProvider.ZOHO_MAIL: "Zoho Mail",
    SecretProvider.ZOHO_CALENDAR: "Zoho Calendar",
    SecretProvider.SLACK: "Slack",
    SecretProvider.PIPEDRIVE: "Pipedrive",
}


def _repo_scoped_profile_line(label: str, base: str, scope: str, scope_kind: str, repos: list[str]) -> str:
    """Render the agents_md line for a repo-scoped provider (GitHub/Bitbucket).

    With repos configured, each --profile slug is mapped to the ``scope/repo`` it
    targets (``github-work`` -> ``aai-labs/agent-farm``) so an agent with several repos
    knows which profile is which. With none configured, the profile carries no ``repo``,
    so aai-cli requires ``--repo`` at call time — the line says so, and names the
    ``scope`` (owner/workspace). ``scope`` comes from the configured secret, so this
    reflects whatever org/workspace the operator set up — nothing is hardcoded.
    """
    if repos:
        segments = ", ".join(f"`--profile {name}` → {scope}/{repo}" for name, repo in _profile_repo_pairs(base, repos))
        return f"- **{label}**: {segments}"
    return (
        f"- **{label}**: `--profile {base}` ({scope_kind} `{scope}` already set on the "
        "profile; no repo configured — pass `--repo <repo>`)"
    )


def build_integrations_policy_md(
    decrypted: Mapping[SecretProvider, SecretContent],
) -> str:
    """Render the concise integrations + policy block injected into agents_md.

    Both Hermes and OpenClaw auto-load AGENTS.md into the startup system prompt, so
    this is where the ``--profile`` mapping belongs. Kept short: a no-fallback policy
    line, the nested command grammar with one worked example (agents otherwise burn
    turns guessing subcommands), one line per configured provider (GitHub/Bitbucket map
    each --profile slug to the repo it targets, or say to pass ``--repo`` when the
    profile has none), and a read-the-file pointer to the on-demand skill docs. Full command
    syntax stays in the per-service
    ``./skills/aai-cli/<service>_skill.md`` files and TOOLS.md. Returns "" when no
    integrations are configured.
    """
    if not decrypted:
        return ""

    lines: list[str] = [
        "\n## Integrations (aai-cli)\n",
        (
            "These integrations are pre-configured. **aai-cli is the only way to reach "
            "them** — always pass `--profile <slug>`. Never fall back to a browser, "
            "`curl`, or raw HTTP, and never invent URLs or tokens.\n"
        ),
        (
            "Commands nest as `aai-cli --profile <slug> <service> <resource> <verb>` "
            "(e.g. `aai-cli --profile jira-work jira issues get AF-147`). Don't guess "
            "subcommands — **Read** the matching `./skills/aai-cli/<service>_skill.md` "
            "file first (they are plain files, not lookup-by-name skills).\n"
        ),
    ]
    for provider in SecretProvider:  # fixed enum order for deterministic output
        content = decrypted.get(provider)
        if content is None or provider not in PROFILE_SLUGS:
            continue
        base = PROFILE_SLUGS[provider]
        if isinstance(content, GithubContent):
            lines.append(_repo_scoped_profile_line("GitHub", base, content.owner, "owner", content.repos))
        elif isinstance(content, BitbucketContent):
            lines.append(_repo_scoped_profile_line("Bitbucket", base, content.workspace, "workspace", content.repos))
        else:
            lines.append(f"- **{_INTEGRATION_LABELS[provider]}**: `--profile {base}`")
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
        if content is not None and provider in _PROFILE_BUILDERS:
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
            lines.append(f"printf '%s' \"${env}\" | aai-cli --config {config_path} secrets set {secret_name}")
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
