"""Builders for the aai-cli tool's runtime artifacts (config.toml, setup script, env).

These are pure string/dict builders (no k8s types) consumed by ``start_agent`` to inject an
agent's integration secrets into its pod so the baked-in ``aai-cli`` can use them.

Per-provider behavior lives on the Integration Plugins
(``api/domains/integrations/plugins/``), not here: this module is the aai-cli *adapter*,
so it owns file layout, ordering, and the shared prose, while each provider owns its own
profile block, secret-store entries, and agents_md lines.
"""

from collections.abc import Iterable, Mapping

from api.domains.agents.models import SecretContent, SecretProvider
from api.domains.credential_gateway.models import gateway_token_env_var
from api.domains.integrations.plugins.aai_cli_support import (
    AaiCliPlugin,
    env_var_for,
    secrets_dir,
)
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.providers import AAI_CLI
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS, effective_egress_mode

__all__ = [
    "CONFIG_PATH",
    "CREDENTIAL_FREE_TOOLS",
    "PROFILE_SLUGS",
    "SECRETS_DIR",
    "build_config_toml",
    "build_env",
    "build_integrations_policy_md",
    "build_local_tools_policy_md",
    "build_setup_sh",
    "build_tool_context_md",
    "env_var_for",
    "provider_secrets_map",
    "store_providers_for",
]


def _aai_cli_plugins() -> tuple[AaiCliPlugin, ...]:
    """Every aai-cli provider, in fixed SecretProvider order."""
    return tuple(p for p in INTEGRATION_PLUGINS.for_tool(AAI_CLI) if isinstance(p, AaiCliPlugin))


def _plugin_for(provider: SecretProvider) -> AaiCliPlugin | None:
    """The aai-cli plugin for a provider, or None when another CLI reaches it."""
    plugin = INTEGRATION_PLUGINS.require(provider)
    return plugin if isinstance(plugin, AaiCliPlugin) else None


# Maps each provider to its (secret_name, content_attr) pairs for the aai-cli encrypted
# secret store. Providers not listed here don't use the store (env-based only, e.g.
# zoho_calendar). Derived from the plugins so a new provider cannot forget to appear.
provider_secrets_map: dict[str, list[tuple[str, str]]] = {
    p.key: list(p.aai_cli_secret_entries) for p in _aai_cli_plugins() if p.aai_cli_secret_entries
}

# Canonical aai-cli --profile slug per provider — the single source of truth shared by the
# config.toml profile builders (which emit `[profiles.<slug>]`) and the markdown that tells
# the agent which --profile to pass. GitHub/Bitbucket use this as the base slug; each extra
# configured repo appends -2, -3, ... via profile_repo_pairs.
PROFILE_SLUGS: dict[SecretProvider, str] = {p.provider: p.aai_cli_slug for p in _aai_cli_plugins()}

# Default config dir for OpenClaw (node user). Callers can pass a different home_dir for other
# runtimes (e.g. Hermes runs as root -> home_dir="/root").
SECRETS_DIR = secrets_dir("/home/node")
CONFIG_PATH = f"{SECRETS_DIR}/config.toml"


def _header(dir_path: str) -> str:
    return f'secrets_file = "{dir_path}/aai-secrets.enc.json"\nkey_file = "{dir_path}/key"\n'


# Every provider reachable through an aai-cli --profile gets a "Configured Integrations"
# line. This was previously limited to the four repo/issue trackers, which left Slack,
# Gmail, Zoho Mail, Pipedrive, and the calendars with no "credentials are already in
# place" note at all — so those agents would tell the user they had no access, or ask for
# a token that was already mounted.
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
    for provider in SecretProvider:  # fixed enum order for deterministic output
        content = decrypted.get(provider)
        plugin = _plugin_for(provider)
        if content is None or plugin is None:
            continue
        lines.append(plugin.aai_cli_context_line(content))
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
        plugin = _plugin_for(provider)
        if content is None or plugin is None:
            continue
        line = plugin.aai_cli_policy_line(content)
        capability = plugin.aai_cli_capability
        lines.append(f"{line} — {capability}" if capability else line)
    return "\n".join(lines) + "\n"


def build_config_toml(
    decrypted: Mapping[SecretProvider, SecretContent],
    home_dir: str = "/home/node",
    *,
    gateway_enabled: bool = False,
    gateway_base_url: str = "",
) -> str:
    """Render config.toml with one profile per provider present in ``decrypted``.

    Providers are emitted in a fixed (enum) order for deterministic output. Store-based providers
    reference their secret via ``*_secret``; env-based providers via ``*_env`` (token not injected).
    """
    dir_path = secrets_dir(home_dir)
    blocks = [_header(dir_path)]
    for provider in SecretProvider:
        content = decrypted.get(provider)
        plugin = _plugin_for(provider)
        if content is None or plugin is None:
            continue
        if effective_egress_mode(plugin, gateway_enabled) is EgressMode.GATEWAY_PROXY:
            blocks.append(
                plugin.aai_cli_gateway_profile_block(
                    content,
                    base_url=f"{gateway_base_url.rstrip('/')}/p/{plugin.key}",
                    token_env=gateway_token_env_var(provider),
                )
            )
        else:
            blocks.append(plugin.aai_cli_profile_block(content))
    return "\n".join(blocks)


def build_setup_sh(
    store_providers: list[SecretProvider],
    home_dir: str = "/home/node",
) -> str:
    """Render the in-pod setup script: install config.toml, then `secrets set` per store secret.

    The ``cp`` always runs (installs the mounted config); `secrets set` lines are emitted only for
    store-based providers (``store_providers``), one line per secret name.
    """
    dir_path = secrets_dir(home_dir)
    config_path = f"{dir_path}/config.toml"
    present = set(store_providers)
    lines = [
        "#!/bin/sh",
        "set -e",
        f"export HOME={home_dir}",
        f"mkdir -p {dir_path}",
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


def store_providers_for(
    decrypted: Mapping[SecretProvider, SecretContent],
    gateway_enabled: bool = False,
) -> dict[SecretProvider, SecretContent]:
    """Narrow a provider map to the ones whose credential still belongs in the pod.

    A provider routed through the gateway is excluded here, which is what actually keeps
    its real credential out of the pod Secret and out of ``aai-secrets.enc.json`` — the
    profile block alone would not.
    """
    keep: dict[SecretProvider, SecretContent] = {}
    for provider, content in decrypted.items():
        plugin = _plugin_for(provider)
        if plugin is None or provider.value not in provider_secrets_map:
            continue
        if effective_egress_mode(plugin, gateway_enabled) is EgressMode.GATEWAY_PROXY:
            continue
        keep[provider] = content
    return keep
