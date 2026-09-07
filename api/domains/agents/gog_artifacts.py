"""Builders for the gog CLI's runtime artifacts (env, shim, agent policy).

Parallel to ``aai_cli_artifacts`` but for a different tool: gog (gogcli) reaches Google
Workspace, so it shares nothing with aai-cli's profile/secret-store machinery. These are
pure string/dict builders consumed by ``start_agent``.

gog is always brokered through the credential gateway (see
``docs/features/integrations.md``): the refresh token and OAuth client secret never leave
the gateway, and the pod's ``gog-shim.sh`` exchanges its Gateway Token for a short-lived
access token on every invocation. Nothing gog-related is persisted in the pod.
"""

from api.domains.agents.models import GoogleWorkspaceContent, SecretProvider
from api.domains.credential_gateway.models import gateway_token_env_var

# Where gog keeps its runtime state, relative to a runtime's home dir. Deliberately on
# the container filesystem and NOT on the PVC. Note that ``start_agent`` separately
# computes an ``aai_home`` that IS the Hermes PVC (/opt/data) — these are two different
# "home" concepts and must not be unified.
#
# The caller passes /home/node (OpenClaw) or /home/hermes (Hermes). /home/hermes exists
# only because hermes-base creates and chowns it: the hermes user's actual home is the
# PVC, and /home is root-owned, so the agent could not write here otherwise.
_CONFIG_SUBDIR = ".config/gogcli"

# Human-facing labels and one worked example per service, for the agent policy block.
_SERVICE_GUIDE: dict[str, tuple[str, str]] = {
    "gmail": ("Gmail", "gog gmail search 'is:unread newer_than:7d'"),
    "calendar": ("Calendar", "gog calendar events list --today"),
    "drive": ("Drive", "gog drive files list"),
    "sheets": ("Sheets", "gog sheets values get <spreadsheet-id> 'Sheet1!A1:D20'"),
}


def gog_home(home_dir: str) -> str:
    """Absolute GOG_HOME for a runtime whose home directory is ``home_dir``."""
    return f"{home_dir}/{_CONFIG_SUBDIR}"


#: The shim exports this before exec'ing the real binary. gog reads it as a root flag
#: (internal/cmd/root.go) and uses it as a static token source, checked before any of its
#: own auth dependencies, so no keyring or stored client is needed.
GOG_ACCESS_TOKEN_ENV = "GOG_ACCESS_TOKEN"


def build_gog_env(
    content: GoogleWorkspaceContent,
    home_dir: str,
    *,
    gateway_base_url: str,
) -> dict[str, str]:
    """Env the gog shim needs: where to find gog's state dir and where to mint a token.

    The refresh token and OAuth client secret stay in the gateway; the pod gets only its
    Gateway Token (injected separately as ``AF_GATEWAY_TOKEN_GOOGLE_WORKSPACE``) and the
    mint URL, and the shim exchanges those for a short-lived access token on every
    invocation. No keyring exists to protect, so nothing else belongs here.
    """
    env = {
        "GOG_HOME": gog_home(home_dir),
        "GOG_ACCOUNT_EMAIL": content.email,
        "AF_GATEWAY_TOKEN_URL": f"{gateway_base_url.rstrip('/')}/token",
    }
    if content.read_only:
        # gog's own runtime guard: it rejects mutating API requests before dispatch,
        # independently of the OAuth scopes we requested. Without it a read-only
        # credential relies entirely on Google refusing the write. Set only when
        # read-only — gog reads this with a true-set parser ("1"/"true"/"yes"/"y"/"on"),
        # so an unconditional "0" would work but leaves a misleading env var in the pod.
        env["GOG_READONLY"] = "1"
    return env


#: Where the shim is installed. Prepended to PATH by each runtime's start.sh, so every
#: command the agent runs resolves `gog` here before /usr/local/bin.
SHIM_BIN_SUBDIR = ".local/bin"
#: The real binary, installed by the base images.
_REAL_GOG = "/usr/local/bin/gog"


def shim_bin_dir(home_dir: str) -> str:
    return f"{home_dir}/{SHIM_BIN_SUBDIR}"


def build_gog_shim_sh() -> str:
    """Render the ``gog`` wrapper that fetches a short-lived token before each call.

    Installed ahead of the real binary on PATH and exec's it by absolute path, so there
    is no recursion. Env-driven and secret-free, so it ships in the ConfigMap like the
    other start-up scripts.

    Fetching per invocation rather than once at boot is deliberate: a Google access token
    lasts about an hour and agents run for days, so a boot-time fetch would work until it
    silently stopped. It also means revoking the Agent Secret takes effect on the next
    command rather than the next restart.

    Failures name the real problem instead of letting gog report a confusing Google
    error, and are distinguished so a missing credential does not look like an outage.
    """
    token_env = gateway_token_env_var(SecretProvider.GOOGLE_WORKSPACE)
    return f"""#!/bin/sh
set -eu
umask 077

if [ -z "${{{token_env}:-}}" ] || [ -z "${{AF_GATEWAY_TOKEN_URL:-}}" ]; then
  echo "gog: no Google Workspace credential is configured for this agent" >&2
  exit 78
fi

if ! response=$(curl -fsS -H "Authorization: Bearer ${token_env}" "$AF_GATEWAY_TOKEN_URL"); then
  echo "gog: the credential gateway refused or could not supply Google authorization" >&2
  exit 77
fi

{GOG_ACCESS_TOKEN_ENV}=$(printf '%s' "$response" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p')
if [ -z "${GOG_ACCESS_TOKEN_ENV}" ]; then
  echo "gog: the credential gateway returned no access token" >&2
  exit 77
fi
export {GOG_ACCESS_TOKEN_ENV}

exec {_REAL_GOG} "$@"
"""


def build_gog_shim_install_sh(home_dir: str) -> str:
    """Render the boot script that puts the shim on PATH.

    Replaces the credential-importing setup script under the gateway: there is no
    keyring, no stored OAuth client and no token to import, so installing the wrapper is
    the whole job.
    """
    bin_dir = shim_bin_dir(home_dir)
    return f"""#!/bin/sh
set -e
umask 077
mkdir -p {bin_dir}
cp /app/config/gog-shim.sh {bin_dir}/gog
chmod 755 {bin_dir}/gog
"""


def build_gog_policy_md(content: GoogleWorkspaceContent | None) -> str:
    """Render the agents_md block for a configured Google Workspace credential.

    Both runtimes auto-load AGENTS.md into the startup prompt, and this block is the
    *only* place the agent learns gog exists (the integration ships no skill file), so it
    carries the command grammar and one worked example per enabled service rather than
    pointing at a doc to read.

    Kept separate from ``build_integrations_policy_md`` because that block tells the agent
    to always pass ``--profile`` and that aai-cli is the only way to reach its
    integrations — both wrong for gog.
    """
    if content is None:
        return ""

    services = [s for s in content.services if s in _SERVICE_GUIDE]
    labels = ", ".join(_SERVICE_GUIDE[s][0] for s in services)
    lines = [
        "\n## Google Workspace (gog)\n",
        (
            f"The Google account **{content.email}** is already connected via the `gog` "
            f"CLI, covering: {labels}. Credentials are in place — **never ask the user "
            "to authenticate, paste a token, or visit a Google page.**\n"
        ),
        (
            "`gog` is a **separate tool from aai-cli**: it takes no `--profile`, and the "
            "aai-cli instructions do not apply to it. The account is already selected, "
            "so no `--account` flag is needed either.\n"
        ),
        (
            "Commands nest as `gog <service> <resource> <verb>`. Pass `--json` when you "
            "need to parse the output. Run `gog <service> --help` to discover "
            "subcommands instead of guessing.\n"
        ),
    ]
    if content.read_only:
        lines.append(
            "**This credential is read-only.** Attempts to send, create, modify, or "
            "delete anything are rejected by `gog` before the request reaches Google. "
            "Do not promise the user a write action — tell them the connection is "
            "read-only.\n"
        )
    lines.append("Available now:\n")
    lines.extend(f"- **{_SERVICE_GUIDE[s][0]}**: `{_SERVICE_GUIDE[s][1]}`" for s in services)
    lines.append(
        "\nNever fall back to a browser, `curl`, or raw Google API calls, and never "
        "invent URLs, spreadsheet IDs, or message IDs — look them up with a `gog` "
        "command first.\n"
    )
    return "\n".join(lines)
