"""Builders for the aai-cli tool's runtime artifacts (config.toml, setup script, env).

These are pure string/dict builders (no k8s types) consumed by ``start_agent`` to inject an
agent's integration secrets into its pod so the baked-in ``aai-cli`` can use them.
"""

from collections.abc import Callable, Iterable, Mapping

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
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
    SecretProvider.ZOHO_MAIL: _zoho_mail_block,
    SecretProvider.ZOHO_CALENDAR: _zoho_calendar_block,
    SecretProvider.SLACK: _slack_block,
    SecretProvider.PIPEDRIVE: _pipedrive_block,
}


# Every provider reachable through an aai-cli --profile gets a "Configured Integrations"
# line. This was previously limited to the four repo/issue trackers, which left Slack,
# Gmail, Zoho Mail, Pipedrive, and the calendars with no "credentials are already in
# place" note at all — so those agents would tell the user they had no access, or ask for
# a token that was already mounted. Keyed off PROFILE_SLUGS so a new provider is covered
# the moment it gets a profile.
_TOOL_CONTEXT_PROVIDERS = frozenset(PROFILE_SLUGS)


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
        if content is None or provider not in PROFILE_SLUGS:
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
        else:
            # Providers with no site/repo metadata worth printing still belong here: the
            # point of this block is "credentials are already in place", which is exactly
            # what a Slack- or Gmail-only agent was missing.
            lines.append(f"- **{_INTEGRATION_LABELS[provider]}** (`{PROFILE_SLUGS[provider]}`)")
    return "\n".join(lines) + "\n"


# Capabilities that need no credential, keyed by the seeded skill name.
#
# The integrations block above is built from configured secrets, so a tool with no
# provider can never appear there — and its skill pointer only reaches TOOLS.md, which the
# runtimes do not auto-load. Without this the agent simply never learns the capability
# exists. Listed only when the skill is actually mounted, since these are opt-in.
CREDENTIAL_FREE_TOOLS: dict[str, str] = {
    "Excel": (
        "- **Excel / CSV** (local files): `aai-cli excel <resource> <verb>` — create workbooks, "
        "add/delete/rename sheet tabs, and read and write cell ranges in "
        "`.xlsx`/`.xlsm` and `.csv`/`.tsv` on disk (`.xls`/`.xlsb`/`.ods` are read-only). "
        "**This is the only supported way to build or edit a spreadsheet.** Do not write "
        "Python, and do not reach for `openpyxl`, `pandas`, `xlsxwriter` or a hand-rolled "
        "zip — they are not installed and produce files Excel may reject. "
        "Read `./skills/aai-excel/SKILL.md` for the command shapes."
    ),
}


def build_local_tools_policy_md(mounted_skill_names: Iterable[str]) -> str:
    """Render the agents_md block for mounted credential-free tools.

    Kept separate from the integrations block because that one tells the agent to always
    pass ``--profile``, which is exactly wrong here — these take no profile and no
    credentials.

    A tool that produces files is only half useful if the agent cannot hand one back, and
    naming the file in prose does not attach it. Both runtimes attach on a ``MEDIA:<path>``
    token in the reply — Hermes matches it anywhere, OpenClaw also has a line-start-only
    path, so the guidance insists on its own line to satisfy both.
    """
    lines = [CREDENTIAL_FREE_TOOLS[name] for name in mounted_skill_names if name in CREDENTIAL_FREE_TOOLS]
    if not lines:
        return ""
    block = (
        "\n## Local file tools (aai-cli)\n\n"
        "These work on files on this machine. They need **no credentials and no "
        "`--profile`** — do not ask the user to authenticate for them.\n\n" + "\n".join(lines) + "\n"
    )
    block += (
        "\nWrite files you intend to share into `/workspace` — it persists across restarts "
        "and is readable by the messaging layer.\n"
    )
    block += (
        "\n**Always send back a file you produced.** When you create or update a file the "
        "user asked for, attach it in that same reply — do not wait to be asked, and do "
        "not just tell them where you saved it. A path they cannot open is not an answer.\n"
        "\nAttach it by putting `MEDIA:<absolute path>` **on its own line** at the end of the "
        "reply:\n\n"
        "```\n"
        "Here's the Q1 report.\n"
        "MEDIA:/workspace/q1-report.xlsx\n"
        "```\n\n"
        "Naming the file in prose does **not** attach it — delivery only happens when that "
        "token is present. Keep it on its own line and keep the path absolute: one runtime "
        "only scans line starts, so a token buried mid-sentence is silently ignored.\n"
    )
    return block


# Display label per provider for the agents_md integrations block.
_INTEGRATION_LABELS: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "GitHub",
    SecretProvider.JIRA: "Jira",
    SecretProvider.CONFLUENCE: "Confluence",
    SecretProvider.BITBUCKET: "Bitbucket",
    SecretProvider.ZOHO_MAIL: "Zoho Mail",
    SecretProvider.ZOHO_CALENDAR: "Zoho Calendar",
    SecretProvider.SLACK: "Slack",
    SecretProvider.PIPEDRIVE: "Pipedrive",
}

# One-clause summary of what each integration can actually do, appended to its agents_md
# line. Without it the always-loaded context named a --profile slug and nothing else, so
# an agent asked "are there files in this channel?" had no token in context linking the
# question to `slack-work` and would answer that it had no access — the profile slug alone
# never told it what the profile was *for*. Sourced from the command surface documented in
# ``aai_cli_skills/bundled/skills/aai-<provider>/SKILL.md``; keep it in sync when
# commands are added. Providers with no bundled aai-cli skill doc (the calendars)
# are omitted and render as before.
_INTEGRATION_CAPABILITIES: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "PRs (diff, files, reviews, comments), issues, branches, repo source, Actions runs",
    SecretProvider.JIRA: "issues (comments, attachments), sprints, boards, projects, users",
    SecretProvider.CONFLUENCE: "pages (comments, attachments), spaces",
    SecretProvider.BITBUCKET: "PRs (diff, comments), commits, branches, repo source, pipelines",
    SecretProvider.ZOHO_MAIL: "read and search mail (read-only)",
    SecretProvider.SLACK: (
        "read channel data: list channels, list and download files and attachments, "
        "read bookmarks, links, canvases (read-only)"
    ),
    SecretProvider.PIPEDRIVE: "deals, leads, persons, organizations, activities, notes, mailbox",
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
    profile has none) closing with a one-clause summary of what that integration can do —
    a bare slug left agents unable to connect a user's question to the profile that
    answers it — and a read-the-file pointer to the on-demand skill docs. Full command
    syntax stays in the per-service
    ``./skills/aai-<integration>/SKILL.md`` files and TOOLS.md. Returns "" when no
    integrations are configured.
    """
    if not (decrypted.keys() & set(PROFILE_SLUGS)):
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
            "subcommands — **Read** the matching `./skills/aai-<integration>/SKILL.md` "
            "file first (they are plain files, not lookup-by-name skills).\n"
        ),
    ]
    for provider in SecretProvider:  # fixed enum order for deterministic output
        content = decrypted.get(provider)
        if content is None or provider not in PROFILE_SLUGS:
            continue
        base = PROFILE_SLUGS[provider]
        if isinstance(content, GithubContent):
            line = _repo_scoped_profile_line("GitHub", base, content.owner, "owner", content.repos)
        elif isinstance(content, BitbucketContent):
            line = _repo_scoped_profile_line("Bitbucket", base, content.workspace, "workspace", content.repos)
        else:
            line = f"- **{_INTEGRATION_LABELS[provider]}**: `--profile {base}`"
        capability = _INTEGRATION_CAPABILITIES.get(provider)
        lines.append(f"{line} — {capability}" if capability else line)
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
