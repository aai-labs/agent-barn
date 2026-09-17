#!/bin/sh
set -e
export PYTHONPATH="/app/config${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p /tmp/agentbarn-bin
printf '#!/bin/sh\nexec python3 /app/config/agentbarn_message.py "$@"\n' > /tmp/agentbarn-bin/agentbarn-message
chmod 755 /tmp/agentbarn-bin/agentbarn-message
export PATH="/tmp/agentbarn-bin:$PATH"

# OpenClaw 2026.8 refuses to start when a pre-migration workspace state is
# present. The markers are runtime-owned and doctor removes them atomically;
# only invoke its broader repair on an affected PVC, never on ordinary boots.
workspace=/home/node/.openclaw/workspace
state_dir=/home/node/.openclaw
has_legacy_workspace_state() {
  [ -e "$workspace/openclaw-workspace-state.json" ] ||
    [ -e "$workspace/.openclaw/workspace-state.json" ] ||
    find "$state_dir/workspace-attestations" -maxdepth 1 -type f \
      \( -name '*.attested' -o -name '*.attested.doctor-importing' \) -print -quit 2>/dev/null \
      | grep -q . ||
    find "$(dirname "$workspace")" -maxdepth 1 -type f \
      \( -name 'workspace.attested' -o -name 'workspace.attested.doctor-importing' \) -print -quit 2>/dev/null \
      | grep -q .
}
if has_legacy_workspace_state; then
  echo "[start] Migrating legacy OpenClaw workspace state"
  openclaw doctor --fix --non-interactive
fi
unset workspace state_dir

node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
node /app/config/init-openclaw.js

PLUGIN_DIR="/home/node/.openclaw/local-plugins/telemetry-push"
mkdir -p "$PLUGIN_DIR"
cp /app/config/telemetry-push-index.js "$PLUGIN_DIR/index.js"
cp /app/config/telemetry-push-package.json "$PLUGIN_DIR/package.json"
cp /app/config/telemetry-push-plugin.json "$PLUGIN_DIR/openclaw.plugin.json"
# Loaded only for native channel Connections via plugins.load.paths.
OBSERVER_DIR="/home/node/.openclaw/local-plugins/agentbarn-observer"
mkdir -p "$OBSERVER_DIR"
cp /app/config/agentbarn-observer-index.js "$OBSERVER_DIR/index.js"
cp /app/config/agentbarn-observer-package.json "$OBSERVER_DIR/package.json"
cp /app/config/agentbarn-observer-plugin.json "$OBSERVER_DIR/openclaw.plugin.json"
# Every plugins.load.paths entry must exist before any openclaw CLI call validates the config.
MESSAGE_PLUGIN_DIR="/home/node/.openclaw/local-plugins/agentbarn-messaging"
mkdir -p "$MESSAGE_PLUGIN_DIR"
cp /app/config/openclaw-messaging.js "$MESSAGE_PLUGIN_DIR/index.js"
printf '{"name":"agentbarn-messaging","type":"module","openclaw":{"extensions":["./index.js"]}}' > "$MESSAGE_PLUGIN_DIR/package.json"
printf '{"id":"agentbarn-messaging","name":"Agent Barn messaging","configSchema":{"type":"object","additionalProperties":false,"properties":{}}}' > "$MESSAGE_PLUGIN_DIR/openclaw.plugin.json"

# Official plugins install from npm at the core's version: OpenClaw only grants plugin
# state to npm installs it recorded, and those records live on the PVC. A reinstall
# fails once present, so skip plugins already at the core's version.
OPENCLAW_VERSION="$(openclaw --version | cut -d' ' -f2)"
install_plugin() {
  installed="$(cat /home/node/.openclaw/npm/projects/openclaw-*/node_modules/"$1"/package.json 2>/dev/null | jq -r .version | head -n 1)"
  [ "$installed" = "$OPENCLAW_VERSION" ] && return 0
  flag=""
  [ -n "$installed" ] && flag="--force"
  openclaw plugins install "$1@$OPENCLAW_VERSION" --accept-capabilities $flag 2>&1 || echo "[start] $1 plugin install failed"
}
install_plugin @openclaw/firecrawl-plugin
for channel in $(echo "${AGENTBARN_NATIVE_CHANNELS:-}" | tr ',' ' '); do
  # Telegram ships inside the core package; there is no @openclaw/telegram.
  [ "$channel" = telegram ] && continue
  install_plugin "@openclaw/$channel"
done

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || echo "[gog] setup failed; continuing"
fi
export AGENTBARN_MESSAGE_SPOOL=/home/node/.openclaw/agentbarn-messages.sqlite3
# Native channel agents set 0 in their Secret so OpenClaw delivers cron results itself.
export AGENTBARN_SCHEDULED_DELIVERY="${AGENTBARN_SCHEDULED_DELIVERY:-1}"
if [ "${AGENTBARN_SCHEDULED_DELIVERY}" = "1" ]; then
  python3 /app/config/agentbarn_message.py drain &
fi
exec openclaw gateway --allow-unconfigured
