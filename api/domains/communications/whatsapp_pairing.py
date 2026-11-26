"""Link a phone to an Agent's WhatsApp Connection by scanning a QR code.

The Agent's own pod runs its runtime's WhatsApp login, so the linked device's keys
are written straight to the Agent's PVC and never pass through Agent Barn. Only the
short-lived QR code and the linked number come back: Hermes' bridge prints the QR
payload, which the dashboard draws; OpenClaw's gateway returns a rendered PNG.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentStatus, AgentType
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.kubernetes.client import KubernetesClient

# How long one pairing attempt may run. WhatsApp rotates the QR code about every
# 20 seconds and stops offering new ones after a few minutes.
PAIRING_SECONDS = 150
# The API's own bound on an attempt's stream: the script's limit plus its last call.
STREAM_SECONDS = PAIRING_SECONDS + 60
# The scripts run as `sh -c SCRIPT MARKER [replace]`, so the marker in a process's
# command line identifies an attempt.
_MARKER = "agentbarn-whatsapp-pairing"

# One attempt runs at a time per Agent. A new one ends an earlier one first, whose
# browser has usually gone: the exec'd script outlives its stream, and would otherwise
# hold the lock until its own time limit. `stop` kills a PID only if its command line
# still names the expected program, since a PID file can outlive its process.
_ATTEMPT_LOCK = """
set -u
owned() { [ -n "${1:-}" ] && tr '\\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q -- "$2"; }
children() {
  for stat in /proc/[0-9]*/stat; do
    read -r pid _ _ ppid _ < "$stat" 2>/dev/null && [ "$ppid" = "$1" ] && echo "$pid"
  done
}
kill_tree() { for child in $(children "$1"); do kill_tree "$child"; done; kill "$1" 2>/dev/null; }
take_lock() {
  exec 9>"$1.lock"
  if ! flock -n 9; then
    holder="$(cat "$1.holder" 2>/dev/null)"
    if owned "$holder" "$0"; then kill_tree "$holder"; fi
    flock -w 10 9 || { echo '{"event":"error","error":"busy"}'; exit 0; }
  fi
  echo $$ > "$1.holder"
}
"""

# Pairs into a staging directory, then swaps it in as the adapter's session, so a
# failed or abandoned attempt never touches a working link. A bridge already running
# on the old session is stopped first: it writes to its session by path and would
# otherwise overwrite the new keys. The session lives where the adapter looks for it:
# Hermes keeps a legacy whatsapp/session that holds files. A new link never logs the
# old one out, so this needs no confirmation.
_HERMES_PAIRING_SCRIPT = (
    _ATTEMPT_LOCK
    + f"""
home="${{HERMES_HOME:-/opt/data}}"
root="$home/platforms/whatsapp"
if [ -n "$(ls -A "$home/whatsapp/session" 2>/dev/null)" ]; then root="$home/whatsapp"; fi
staging="$root/pairing"
mkdir -p "$root"
take_lock "$root/pairing"
rm -rf "$staging"
cd "${{WHATSAPP_BRIDGE_DIR:-/opt/hermes/scripts/whatsapp-bridge}}" || exit 0
WHATSAPP_MODE=bot timeout {PAIRING_SECONDS} node bridge.js --pair-only --pair-json --session "$staging"
code=$?
if [ "$code" -eq 124 ]; then echo '{{"event":"expired"}}'; fi
if [ "$code" -ne 0 ] || [ ! -f "$staging/creds.json" ]; then rm -rf "$staging"; exit 0; fi
bridge="$(head -n 1 "$root/session/bridge.pid" 2>/dev/null)"
if owned "$bridge" bridge.js; then kill "$bridge"; fi
rm -rf "$root/session.previous"
if [ -d "$root/session" ]; then mv "$root/session" "$root/session.previous"; fi
mv "$staging" "$root/session" && rm -rf "$root/session.previous" && echo '{{"event":"linked"}}'
"""
)

# OpenClaw's running gateway owns the WhatsApp login, so the script drives its
# web.login.start / web.login.wait methods rather than a second WhatsApp client. Each
# wait returns when the QR rotates, the phone links, or its own timeout passes. The
# gateway won't offer a QR while a phone is linked; it says so, and only `replace`
# (after the person confirms) logs that phone out to start again. Once linked, the
# gateway starts the channel itself.
_OPENCLAW_PAIRING_SCRIPT = (
    _ATTEMPT_LOCK
    + f"""
mkdir -p "$HOME/.openclaw"
take_lock "$HOME/.openclaw/whatsapp-pairing"
force=false
if [ "${{1:-}}" = replace ]; then force=true; fi
call() {{ openclaw gateway call "$1" --json --params "$2" --timeout "$3" 2>/dev/null; }}
deadline=$(( $(date +%s) + {PAIRING_SECONDS} ))
# The gateway starts only after start.sh installs @openclaw/whatsapp, which takes
# minutes on an Agent's first start with WhatsApp.
reply=$(call web.login.start "$(jq -cn --argjson force "$force" '{{timeoutMs:30000,force:$force}}')" 45000) || {{
  if call health '{{}}' 10000 >/dev/null; then echo '{{"event":"error"}}'; else echo '{{"event":"error","error":"starting"}}'; fi
  exit 0
}}
if [ "$(printf '%s' "$reply" | jq -r '.connected')" = true ]; then
  echo '{{"event":"connected"}}'; echo '{{"event":"linked"}}'; exit 0
fi
qr=$(printf '%s' "$reply" | jq -r '.qrDataUrl // empty')
if [ -z "$qr" ]; then
  message=$(printf '%s' "$reply" | jq -r '.message // ""')
  case "$message" in
    *"already linked"*)
      phone="${{message#*already linked (}}"; phone="${{phone%%)*}}"
      jq -cn --arg phone "$phone" '{{event:"already_linked",phone:$phone}}' ;;
    *) echo '{{"event":"error"}}' ;;
  esac
  exit 0
fi
jq -cn --arg image "$qr" '{{event:"qr_image",image:$image}}'
while [ "$(date +%s)" -lt "$deadline" ]; do
  reply=$(call web.login.wait "$(jq -cn --arg qr "$qr" '{{timeoutMs:20000,currentQrDataUrl:$qr}}')" 35000) || {{ echo '{{"event":"error"}}'; exit 0; }}
  if [ "$(printf '%s' "$reply" | jq -r '.connected')" = true ]; then
    echo '{{"event":"connected"}}'; echo '{{"event":"linked"}}'; exit 0
  fi
  next=$(printf '%s' "$reply" | jq -r '.qrDataUrl // empty')
  if [ -n "$next" ]; then qr="$next"; jq -cn --arg image "$qr" '{{event:"qr_image",image:$image}}'; continue; fi
  case "$(printf '%s' "$reply" | jq -r '.message // ""')" in
    "Still waiting"*) ;;
    *expired*) echo '{{"event":"expired"}}'; exit 0 ;;
    *"logged out"*|*"Logged out"*) echo '{{"event":"error","error":"logged_out"}}'; exit 0 ;;
    *) echo '{{"event":"error"}}'; exit 0 ;;
  esac
done
echo '{{"event":"expired"}}'
"""
)

_PAIRING_SCRIPTS = {AgentType.HERMES: _HERMES_PAIRING_SCRIPT, AgentType.OPENCLAW: _OPENCLAW_PAIRING_SCRIPT}

# A PNG data URL, as OpenClaw renders its QR code; anything else is dropped.
_QR_IMAGE_PREFIX = "data:image/png;base64,"
_PHONE = re.compile(r"^\+[0-9]{7,15}$")

_ERRORS = {
    "busy": "Another Link phone attempt is already running for this Agent.",
    "logged_out": "WhatsApp refused the link. Try again from Linked devices on the phone.",
    "starting": "The Agent is still starting. On its first start with WhatsApp this takes a few minutes; try again then.",
}


def pairing_event(line: str) -> dict | None:
    """The client-safe form of one bridge output line, or None for anything else.

    The bridge also prints its own warnings on stdout, so only the pairing events
    pass, rebuilt field by field.
    """
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    event = raw.get("event")
    if event == "qr" and isinstance(raw.get("qr"), str):
        return {"event": "qr", "qr": raw["qr"]}
    if event == "qr_image" and isinstance(raw.get("image"), str) and raw["image"].startswith(_QR_IMAGE_PREFIX):
        return {"event": "qr_image", "image": raw["image"]}
    if event == "connected":
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        # "15551234567:12@s.whatsapp.net": the number, then the device.
        number = str(user.get("id") or "").split("@", 1)[0].split(":", 1)[0]
        return {"event": "connected", "phone": f"+{number}" if number.isdigit() else None}
    if event == "already_linked":
        phone = str(raw.get("phone") or "")
        return {"event": "already_linked", "phone": phone if _PHONE.match(phone) else None}
    if event == "linked":
        return {"event": "linked"}
    if event == "expired":
        return {"event": "expired"}
    if event == "error":
        return {"event": "error", "message": _ERRORS.get(str(raw.get("error")), "WhatsApp pairing failed.")}
    return None


@inject
@singleton
@dataclass
class WhatsAppPairingService:
    config: Config
    authorization: AgentAuthorization
    repository: CommunicationConnectionRepository
    k8s: KubernetesClient

    def pair(
        self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext, *, replace: bool = False
    ) -> Iterator[str | None]:
        """Run one pairing attempt in the Agent's pod, yielding JSON events or None while idle.

        Linking a phone grants the Agent that WhatsApp account, so it takes the same
        permissions as setting a Connection's credentials. ``replace`` lets OpenClaw log
        out a phone that is already linked; without it, the attempt reports that phone.
        """
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        connection = self.repository.get_active_in_scope(connection_id, agent_id, scope)
        if connection is None or connection.platform_key != "whatsapp":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp Connection not found")
        script = _PAIRING_SCRIPTS.get(AgentType(agent.agent_type))
        if script is None or agent.parent_agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="WhatsApp is not available for this Agent"
            )
        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Start the Agent before linking a phone")
        pod = self.k8s.get_pod_name_for_deployment(f"agent-{agent.id}", self.config.k8s_namespace)
        if pod is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="The Agent is not running yet; try again shortly"
            )
        command = ["sh", "-c", script, _MARKER, *(["replace"] if replace else [])]
        return self._events(pod, command)

    def _events(self, pod: str, command: list[str]) -> Iterator[str | None]:
        lines = self.k8s.stream_exec_lines(pod, self.config.k8s_namespace, command, max_seconds=STREAM_SECONDS)
        for line in lines:
            if line is None:
                yield None
            elif (event := pairing_event(line)) is not None:
                yield json.dumps(event)
