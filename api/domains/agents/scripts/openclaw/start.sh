#!/bin/sh
set -e
export AGENT_RUNTIME_SETUP_READY_FILE=/tmp/agentbarn-runtime-setup-ready
rm -f "$AGENT_RUNTIME_SETUP_READY_FILE"
node /app/config/init-openclaw.js
python3 /app/config/retire-messaging.py openclaw /home/node/.openclaw
node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
python3 /app/config/agent-trigger-server.py &

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
sh /app/config/legacy-workspace-migration.sh || echo "[start] legacy workspace migration failed; continuing"

OPENCLAW_VERSION="$(openclaw --version | cut -d' ' -f2)"
# The bin entry resolves to openclaw.mjs at the installed package root.
CORE_DIR="$(dirname "$(readlink -f "$(command -v openclaw)")")"
. /app/config/openclaw-plugins.sh
install_plugin @openclaw/firecrawl-plugin
for channel in $(echo "${AGENTBARN_NATIVE_CHANNELS:-}" | tr ',' ' '); do
  # Telegram ships inside the core package; there is no @openclaw/telegram.
  [ "$channel" = telegram ] && continue
  install_plugin "@openclaw/$channel"
done

# Approved Agent Add-ons, mounted read-only. After the image's own PATH and the
# gog wrapper below, so an add-on can add commands but never replace the runtime's
# (openclaw, node, python3) or one Agent Barn manages.
if [ -n "${AGENTBARN_ADDONS_PATH:-}" ]; then
  export PATH="$PATH:$AGENTBARN_ADDONS_PATH"
fi

# The gog wrapper installs here when Google Workspace is brokered through the
# credential gateway. Ahead of /usr/local/bin so agent commands resolve it first.
export PATH="/home/node/.local/bin:$PATH"

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || exit $?
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || exit $?
fi
if [ -n "${MEMORY_API_KEY:-}" ]; then
  python3 /app/config/memory-gateway-ready.py || true
fi
touch "$AGENT_RUNTIME_SETUP_READY_FILE"
exec openclaw gateway --allow-unconfigured
