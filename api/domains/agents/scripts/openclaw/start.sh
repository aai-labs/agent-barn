#!/bin/sh
set -e
node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
node /app/config/init-openclaw.js

PLUGIN_DIR="/home/node/.openclaw/local-plugins/telemetry-push"
mkdir -p "$PLUGIN_DIR"
cp /app/config/telemetry-push-index.js "$PLUGIN_DIR/index.js"
cp /app/config/telemetry-push-package.json "$PLUGIN_DIR/package.json"
cp /app/config/telemetry-push-plugin.json "$PLUGIN_DIR/openclaw.plugin.json"

openclaw plugins install @openclaw/firecrawl-plugin 2>&1 || echo "[start] firecrawl plugin install failed"

# The gog wrapper installs here when Google Workspace is brokered through the
# credential gateway. Ahead of /usr/local/bin so agent commands resolve it first.
export PATH="/home/node/.local/bin:$PATH"

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || echo "[gog] setup failed; continuing"
fi
exec openclaw gateway --allow-unconfigured
