#!/bin/sh
set -e
export PYTHONPATH="/app/config${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p /tmp/agentbarn-bin
printf '#!/bin/sh\nexec python3 /app/config/agentbarn_message.py "$@"\n' > /tmp/agentbarn-bin/agentbarn-message
chmod 755 /tmp/agentbarn-bin/agentbarn-message
export PATH="/tmp/agentbarn-bin:$PATH"

node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
python3 /app/config/agent-trigger-server.py &
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

sh /app/config/legacy-workspace-migration.sh || echo "[start] legacy workspace migration failed; continuing"

# Official plugins install from npm at the core's version: OpenClaw only grants plugin
# state to npm installs it recorded, and those records live on the PVC. A reinstall
# fails once present, so skip plugins already at the core's version.
#
# Each install also links the core into the plugin from /usr/local, outside the
# volume, so restore points cannot carry that link and a restored tree arrives
# without it. Recreating it is enough: the package and OpenClaw's record of it
# both came back with the volume, and reinstalling over them fails anyway --
# OpenClaw rejects a package whose record it already holds.
OPENCLAW_VERSION="$(openclaw --version | cut -d' ' -f2)"
# The bin entry resolves to openclaw.mjs at the installed package root.
CORE_DIR="$(dirname "$(readlink -f "$(command -v openclaw)")")"
repair_peer_link() {
  # -d follows the link, so this is false when the peer is missing or dangling.
  [ -n "$1" ] && [ ! -d "$1/node_modules/openclaw" ] || return 0
  mkdir -p "$1/node_modules"
  rm -f "$1/node_modules/openclaw"
  ln -s "$CORE_DIR" "$1/node_modules/openclaw"
  echo "[start] recreated the openclaw peer link for $1"
}
install_plugin() {
  pkg_dir="$(ls -d /home/node/.openclaw/npm/projects/openclaw-*/node_modules/"$1" 2>/dev/null | head -n 1)"
  installed="$(cat "$pkg_dir/package.json" 2>/dev/null | jq -r .version | head -n 1)"
  if [ "$installed" = "$OPENCLAW_VERSION" ]; then
    repair_peer_link "$pkg_dir"
    return 0
  fi
  flag=""
  [ -n "$installed" ] && flag="--force"
  openclaw plugins install "$1@$OPENCLAW_VERSION" --accept-capabilities $flag 2>&1 \
    || echo "[start] $1 plugin install failed"
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
