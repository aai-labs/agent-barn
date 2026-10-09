"""Direct Google credential import with disposable runtime state."""

import json
import secrets
from shlex import quote

from api.domains.agents.gog_artifacts import gog_home, shim_bin_dir
from api.domains.agents.models import GoogleWorkspaceContent


def build_direct_gog_env(content: GoogleWorkspaceContent, home_dir: str) -> dict[str, str]:
    if not content.client_id or not content.client_secret or not content.refresh_token:
        raise ValueError("Direct Google Workspace requires the OAuth client and refresh token")
    env = {
        "GOG_HOME": gog_home(home_dir),
        "GOG_ACCOUNT": content.email,
        "GOG_KEYRING_BACKEND": "file",
        "GOG_KEYRING_PASSWORD": secrets.token_urlsafe(32),
        "GOG_CLIENT_JSON": json.dumps(
            {"web": {"client_id": content.client_id, "client_secret": content.client_secret}}
        ),
        "GOG_TOKEN_JSON": json.dumps(
            {
                "email": content.email,
                "client": "default",
                "services": content.services,
                "scopes": content.scopes,
                "refresh_token": content.refresh_token,
            }
        ),
    }
    if content.read_only:
        env["GOG_READONLY"] = "1"
    return env


def build_direct_gog_setup_sh(home_dir: str) -> str:
    """Import via the real binary, avoiding an older broker wrapper on PATH.

    All credentials arrive through Secret environment; the script is credential-free.
    The disposable state directory is fixed by the adapter, never an arbitrary env path.
    """
    state_dir = quote(gog_home(home_dir))
    wrapper = quote(f"{shim_bin_dir(home_dir)}/gog")
    return f"""#!/bin/sh
set -eu
umask 077
if [ "${{GOG_HOME:-}}" != {state_dir} ]; then
  echo "gog: unexpected credential state directory" >&2
  exit 78
fi
rm -f -- {wrapper}
rm -rf -- "$GOG_HOME"
mkdir -p "$GOG_HOME"
client_file=$(mktemp)
trap 'rm -f -- "$client_file"' EXIT HUP INT TERM
printf '%s' "$GOG_CLIENT_JSON" > "$client_file"
/usr/local/bin/gog auth credentials "$client_file"
printf '%s' "$GOG_TOKEN_JSON" | /usr/local/bin/gog auth tokens import -
"""
