"""Builders for the gog CLI's runtime artifacts (env, setup script, agent policy).

Parallel to ``aai_cli_artifacts`` but for a different tool: gog (gogcli) reaches Google
Workspace with its own OAuth refresh token and its own on-disk state, so it shares
nothing with aai-cli's profile/secret-store machinery. These are pure string/dict
builders consumed by ``start_agent``.

The design that these builders encode (see
``docs/features/integrations.md``): the encrypted Agent Secret is the
single source of truth, and the pod's gog state is rebuilt from it on every boot. Nothing
gog-related is persisted in the pod, so the keyring password is regenerated per start and
removing the credential removes access at the next restart.
"""

import json

from api.domains.agents.models import GoogleWorkspaceContent

# Where gog keeps credentials.json + the encrypted file keyring, relative to a runtime's
# home dir. Deliberately on the container filesystem and NOT on the PVC: it is a
# per-boot cache of the DB row, not state worth persisting. Note that ``start_agent``
# separately computes an ``aai_home`` that IS the Hermes PVC (/opt/data) — these are two
# different "home" concepts and must not be unified.
#
# The caller passes /home/node (OpenClaw) or /home/hermes (Hermes). /home/hermes exists
# only because hermes-base creates and chowns it: the hermes user's actual home is the
# PVC, and /home is root-owned, so the agent could not write here otherwise.
_CONFIG_SUBDIR = ".config/gogcli"

# gog reads only client_id/client_secret out of a Google client JSON, and accepts either
# an "installed" or a "web" wrapper key (internal/config/credentials.go). The platform
# consent flow uses a Web-application client, so that is what we synthesize.
_CLIENT_JSON_KEY = "web"

# gog buckets tokens per named OAuth client; the unnamed default bucket is what a plain
# `gog ...` invocation reads (internal/config.DefaultClientName).
_DEFAULT_CLIENT_NAME = "default"

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


def build_gog_env(
    content: GoogleWorkspaceContent,
    home_dir: str,
    keyring_password: str,
) -> dict[str, str]:
    """Env carrying everything ``gog-setup.sh`` needs to rebuild gog's state in the pod.

    ``GOG_TOKEN_JSON`` is the exact payload ``gog auth tokens import`` accepts on stdin
    (internal/cmd/auth_tokens.go). It carries the refresh token, so this whole mapping
    belongs in the pod Secret — never a ConfigMap.
    """
    client_json = json.dumps(
        {
            _CLIENT_JSON_KEY: {
                "client_id": content.client_id,
                "client_secret": content.client_secret,
            }
        }
    )
    token_json = json.dumps(
        {
            "email": content.email,
            "client": _DEFAULT_CLIENT_NAME,
            "services": content.services,
            "scopes": content.scopes,
            "refresh_token": content.refresh_token,
        }
    )
    return {
        "GOG_HOME": gog_home(home_dir),
        "GOG_KEYRING_BACKEND": "file",
        "GOG_KEYRING_PASSWORD": keyring_password,
        "GOG_CLIENT_JSON": client_json,
        "GOG_TOKEN_JSON": token_json,
        "GOG_ACCOUNT_EMAIL": content.email,
    }


def build_gog_setup_sh() -> str:
    """Render the in-pod setup script: install the OAuth client, then import the token.

    Entirely env-driven — no secret material is interpolated here — so it is safe to ship
    in the ConfigMap alongside the other start-up scripts.

    GOG_HOME is wiped first so a boot can never inherit half-written state from a
    previous one (the credential may have changed, or been removed and re-added).

    No default account is set: gog infers the account when exactly one token exists for
    the client (``inferredStoredAccount``), which is always the case here. ``gog auth
    alias set default`` would in fact fail — "default" is a reserved alias name.
    """
    return """#!/bin/sh
set -e
umask 077
rm -rf "$GOG_HOME"
mkdir -p "$GOG_HOME"

client_file="$(mktemp)"
printf '%s' "$GOG_CLIENT_JSON" > "$client_file"
gog auth credentials "$client_file"
rm -f "$client_file"

printf '%s' "$GOG_TOKEN_JSON" | gog auth tokens import -
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
            "delete anything will be refused by Google. Do not promise the user a write "
            "action — tell them the connection is read-only.\n"
        )
    lines.append("Available now:\n")
    lines.extend(f"- **{_SERVICE_GUIDE[s][0]}**: `{_SERVICE_GUIDE[s][1]}`" for s in services)
    lines.append(
        "\nNever fall back to a browser, `curl`, or raw Google API calls, and never "
        "invent URLs, spreadsheet IDs, or message IDs — look them up with a `gog` "
        "command first.\n"
    )
    return "\n".join(lines)
