"""Builders for the aai-cli tool's runtime artifacts (config.toml, setup script, env).

These are pure string/dict builders (no k8s types) consumed by ``start_agent`` to inject an
agent's integration secrets into its pod so the baked-in ``aai-cli`` can use them.

Per-provider behavior lives on the Integration Plugins
(``api/domains/integrations/plugins/``), not here: this module is the aai-cli *adapter*,
so it owns file layout, ordering, and the shared prose, while each provider owns its own
profile block, secret-store entries, and agents_md lines.
"""

from collections.abc import Iterable, Mapping

from api.domains.agents.models import SecretContent, SecretProvider, SharePointContent
from api.domains.credential_gateway.models import gateway_token_env_var
from api.domains.integrations.plugins.aai_cli_support import (
    AaiCliPlugin,
    env_var_for,
    secrets_dir,
)
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.providers import AAI_CLI
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS

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
# secret store. Providers not listed here don't use the store. Derived from the plugins
# so a new provider cannot forget to appear.
provider_secrets_map: dict[str, list[tuple[str, str]]] = {
    p.key: list(p.aai_cli_secret_entries) for p in _aai_cli_plugins() if p.aai_cli_secret_entries
}

# Canonical aai-cli --profile slug per provider — the single source of truth shared by the
# config.toml profile builders (which emit `[profiles.<slug>]`) and the markdown that tells
# the agent which --profile to pass. GitHub/Bitbucket use this as the base slug; each extra
# configured repo appends -2, -3, ... via profile_repo_pairs.
PROFILE_SLUGS: dict[SecretProvider, str] = {p.provider: p.aai_cli_slug for p in _aai_cli_plugins()}

# SharePoint uses aai-cli's own delegated Microsoft profile. aai-cli refreshes the token and
# stores each rotated one under this name, so the pod writes it only for a new sign-in (see
# build_setup_sh); rewriting the original on every boot would end access 90 days after sign-in.
SHAREPOINT_REFRESH_TOKEN_SECRET = "microsoft.sharepoint_refresh_token"
SHAREPOINT_SIGN_IN_ID_ENV = "AAI_SHAREPOINT_SIGN_IN_ID"

# Default config dir for OpenClaw (node user). Callers can pass a different home_dir for other
# runtimes (e.g. Hermes runs as root -> home_dir="/root").
SECRETS_DIR = secrets_dir("/home/node")
CONFIG_PATH = f"{SECRETS_DIR}/config.toml"


def _header(dir_path: str) -> str:
    return f'secrets_file = "{dir_path}/aai-secrets.enc.json"\nkey_file = "{dir_path}/key"\n'


# Every provider reachable through an aai-cli --profile gets a "Configured Integrations"
# line. This was previously limited to the four repo/issue trackers, which left providers
# such as Pipedrive with no "credentials are already in place" note at all — so those
# agents would tell the user they had no access, or ask for a token that was already
# mounted.
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
    credentials. Where to write a file and how to hand it back is
    ``build_file_delivery_policy_md``'s job: it depends on the agent's Connections, not on
    which tool made the file, and an Agent without a native chat Connection cannot share one.
    """
    lines = [CREDENTIAL_FREE_TOOLS[name] for name in mounted_skill_names if name in CREDENTIAL_FREE_TOOLS]
    if not lines:
        return ""
    return (
        "\n## Local file tools (aai-cli)\n\n"
        "These work on files on this machine. They need **no credentials and no "
        "`--profile`** — do not ask the user to authenticate for them.\n\n" + "\n".join(lines) + "\n"
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
    gateway_base_url: str = "",
    store_dir: str | None = None,
) -> str:
    """Render config.toml with one profile per provider present in ``decrypted``.

    Providers are emitted in a fixed (enum) order for deterministic output. Store-based providers
    reference their secret via ``*_secret``; env-based providers via ``*_env`` (token not injected).
    ``store_dir`` places the encrypted secret store (default: beside the config); it must survive
    restarts for tokens aai-cli rotates itself.
    """
    blocks = [_header(store_dir or secrets_dir(home_dir))]
    for provider in SecretProvider:
        content = decrypted.get(provider)
        plugin = _plugin_for(provider)
        if content is None or plugin is None:
            continue
        if plugin.egress_mode is EgressMode.GATEWAY_PROXY:
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
    *,
    store_dir: str | None = None,
    install_config: bool = True,
) -> str:
    """Render the in-pod setup script: install config.toml, then `secrets set` per store secret.

    The ``cp`` always runs (installs the mounted config); `secrets set` lines are emitted only for
    store-based providers (``store_providers``), one line per secret name. SharePoint's refresh
    token is written only when its sign-in id differs from the one recorded beside the store:
    aai-cli rotates that token in the store, and a restart must not put the original back.
    Without SharePoint, a token left from an earlier sign-in is removed. ``install_config=False``
    is for an agent with no aai-cli profiles, which still needs that cleanup.
    """
    config_dir = f"{home_dir}/.config/aai-cli"
    config_path = f"{config_dir}/config.toml"
    store = store_dir or config_dir
    present = set(store_providers)
    lines = [
        "#!/bin/sh",
        "set -e",
        f"export HOME={home_dir}",
        f"mkdir -p {config_dir}" if store == config_dir else f"mkdir -p {config_dir} {store}",
    ]
    if install_config:
        lines.append(f"cp /app/config/aai-cli-config.toml {config_path}")
    for provider in SecretProvider:  # fixed order for determinism
        if provider not in present:
            continue
        for secret_name, _ in provider_secrets_map.get(provider.value, []):
            if provider == SecretProvider.SHAREPOINT:
                continue
            env = env_var_for(secret_name)
            lines.append(f"printf '%s' \"${env}\" | aai-cli --config {config_path} secrets set {secret_name}")
    marker = f"{store}/{SHAREPOINT_REFRESH_TOKEN_SECRET}.sign-in"
    if SecretProvider.SHAREPOINT in present:
        token_env = env_var_for(SHAREPOINT_REFRESH_TOKEN_SECRET)
        lines += [
            f'if [ "$(cat {marker} 2>/dev/null)" != "${SHAREPOINT_SIGN_IN_ID_ENV}" ]; then',
            f"  printf '%s' \"${token_env}\" | aai-cli --config {config_path} secrets set {SHAREPOINT_REFRESH_TOKEN_SECRET}",
            f"  printf '%s' \"${SHAREPOINT_SIGN_IN_ID_ENV}\" > {marker}",
            "fi",
        ]
    else:
        # The store outlives the credential on the agent's volume; don't leave its token behind.
        lines += [
            f"if [ -f {marker} ]; then",
            (
                f"  aai-cli --secrets-file {store}/aai-secrets.enc.json --key-file {store}/key "
                f"secrets remove {SHAREPOINT_REFRESH_TOKEN_SECRET} || true"
            ),
            f"  rm -f {marker}",
            "fi",
        ]
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
        if isinstance(content, SharePointContent):
            env[env_var_for(SHAREPOINT_REFRESH_TOKEN_SECRET)] = content.refresh_token
            env[SHAREPOINT_SIGN_IN_ID_ENV] = content.sign_in_id
    return env


def store_providers_for(
    decrypted: Mapping[SecretProvider, SecretContent],
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
        if plugin.egress_mode is EgressMode.GATEWAY_PROXY:
            continue
        keep[provider] = content
    return keep
