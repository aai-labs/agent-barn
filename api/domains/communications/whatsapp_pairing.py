"""Link a phone to an Agent's WhatsApp Connection by scanning a QR code.

The Agent's own pod runs its runtime's WhatsApp login, so the linked device's keys
are written straight to the Agent's PVC and never pass through Agent Barn. Only the
short-lived QR code and the linked number come back: Hermes' bridge prints the QR
payload, which the dashboard draws; OpenClaw's gateway returns a rendered PNG.
"""

import json
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

# Hermes and OpenClaw differ in who holds the session while pairing, so each has a script.
# How long one pairing attempt may run. WhatsApp rotates the QR code about every
# 20 seconds and stops offering new ones after a few minutes.
PAIRING_SECONDS = 150

# Pairs into a staging directory, then swaps it in as the adapter's session, so a
# failed or abandoned attempt never touches a working link. A bridge already running
# on the old session is stopped first: it writes to its session by path and would
# otherwise overwrite the new keys. One attempt at a time per Agent.
_HERMES_PAIRING_SCRIPT = f"""
set -u
root="${{HERMES_HOME:-/opt/data}}/platforms/whatsapp"
staging="$root/pairing"
mkdir -p "$root"
exec 9>"$root/pairing.lock"
if ! flock -n 9; then echo '{{"event":"error","error":"busy"}}'; exit 0; fi
rm -rf "$staging"
cd /opt/hermes/scripts/whatsapp-bridge || exit 0
WHATSAPP_MODE=bot timeout {PAIRING_SECONDS} node bridge.js --pair-only --pair-json --session "$staging"
code=$?
if [ "$code" -eq 124 ]; then echo '{{"event":"expired"}}'; fi
if [ "$code" -ne 0 ] || [ ! -f "$staging/creds.json" ]; then rm -rf "$staging"; exit 0; fi
if [ -f "$root/session/bridge.pid" ]; then kill "$(head -n 1 "$root/session/bridge.pid")" 2>/dev/null; fi
rm -rf "$root/session.previous"
if [ -d "$root/session" ]; then mv "$root/session" "$root/session.previous"; fi
mv "$staging" "$root/session" && rm -rf "$root/session.previous" && echo '{{"event":"linked"}}'
"""

# OpenClaw's running gateway owns the WhatsApp login, so the script drives its
# web.login.start / web.login.wait methods rather than a second WhatsApp client. Each
# wait returns when the QR rotates, the phone links, or its own timeout passes. A
# linked Agent is logged out first ("force"), because the gateway refuses a new QR
# while a link is active: linking again replaces the current link straight away.
_OPENCLAW_PAIRING_SCRIPT = f"""
set -u
mkdir -p "$HOME/.openclaw"
exec 9>"$HOME/.openclaw/whatsapp-pairing.lock"
if ! flock -n 9; then echo '{{"event":"error","error":"busy"}}'; exit 0; fi
call() {{ openclaw gateway call "$1" --json --params "$2" --timeout "$3" 2>/dev/null; }}
deadline=$(( $(date +%s) + {PAIRING_SECONDS} ))
reply=$(call web.login.start '{{"timeoutMs":30000,"force":true}}' 45000) || {{ echo '{{"event":"error"}}'; exit 0; }}
qr=$(printf '%s' "$reply" | jq -r '.qrDataUrl // empty')
if [ -z "$qr" ]; then echo '{{"event":"error"}}'; exit 0; fi
jq -cn --arg image "$qr" '{{event:"qr_image",image:$image}}'
while [ "$(date +%s)" -lt "$deadline" ]; do
  reply=$(call web.login.wait "$(jq -cn --arg qr "$qr" '{{timeoutMs:20000,currentQrDataUrl:$qr}}')" 35000) \
    || {{ echo '{{"event":"error"}}'; exit 0; }}
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

_PAIRING_SCRIPTS = {AgentType.HERMES: _HERMES_PAIRING_SCRIPT, AgentType.OPENCLAW: _OPENCLAW_PAIRING_SCRIPT}

# A PNG data URL, as OpenClaw renders its QR code; anything else is dropped.
_QR_IMAGE_PREFIX = "data:image/png;base64,"

_ERRORS = {
    "busy": "Another Link phone attempt is already running for this Agent.",
    "logged_out": "WhatsApp refused the link. Try again from Linked devices on the phone.",
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

    def pair(self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext) -> Iterator[str | None]:
        """Run one pairing attempt in the Agent's pod, yielding JSON events or None while idle.

        Linking a phone grants the Agent that WhatsApp account, so it takes the same
        permissions as setting a Connection's credentials.
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
        return self._events(pod, script)

    def _events(self, pod: str, script: str) -> Iterator[str | None]:
        for line in self.k8s.stream_exec_lines(pod, self.config.k8s_namespace, ["sh", "-c", script]):
            if line is None:
                yield None
            elif (event := pairing_event(line)) is not None:
                yield json.dumps(event)
