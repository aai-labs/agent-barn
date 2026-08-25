#!/bin/sh
set -e
node /app/config/healthz-server.js &
node /app/config/init-openclaw.js

PLUGIN_DIR="/home/node/.openclaw/local-plugins/telemetry-push"
mkdir -p "$PLUGIN_DIR"
cp /app/config/telemetry-push-index.js "$PLUGIN_DIR/index.js"
cp /app/config/telemetry-push-package.json "$PLUGIN_DIR/package.json"
cp /app/config/telemetry-push-plugin.json "$PLUGIN_DIR/openclaw.plugin.json"

if [ "$AGENT_PLATFORM" = "slack" ] || [ -z "$AGENT_PLATFORM" ]; then
  openclaw plugins install @openclaw/slack 2>&1 || echo "[start] slack plugin install failed"
fi

if [ "$AGENT_PLATFORM" = "discord" ]; then
  openclaw plugins install @openclaw/discord 2>&1 || echo "[start] discord plugin install failed"
fi

openclaw plugins install @openclaw/firecrawl-plugin 2>&1 || echo "[start] firecrawl plugin install failed"

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || echo "[gog] setup failed; continuing"
fi
exec openclaw gateway --allow-unconfigured
