#!/bin/sh
set -e
export PYTHONPATH="/app/config${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p /tmp/agentbarn-bin
printf '#!/bin/sh\nexec python3 /app/config/agentbarn_message.py "$@"\n' > /tmp/agentbarn-bin/agentbarn-message
chmod 755 /tmp/agentbarn-bin/agentbarn-message
export PATH="/tmp/agentbarn-bin:$PATH"
node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
node /app/config/init-openclaw.js

PLUGIN_DIR="/home/node/.openclaw/local-plugins/telemetry-push"
mkdir -p "$PLUGIN_DIR"
cp /app/config/telemetry-push-index.js "$PLUGIN_DIR/index.js"
cp /app/config/telemetry-push-package.json "$PLUGIN_DIR/package.json"
cp /app/config/telemetry-push-plugin.json "$PLUGIN_DIR/openclaw.plugin.json"

openclaw plugins install @openclaw/firecrawl-plugin 2>&1 || echo "[start] firecrawl plugin install failed"

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || echo "[gog] setup failed; continuing"
fi
MESSAGE_PLUGIN_DIR="/home/node/.openclaw/local-plugins/agentbarn-messaging"
mkdir -p "$MESSAGE_PLUGIN_DIR"
cp /app/config/openclaw-messaging.js "$MESSAGE_PLUGIN_DIR/index.js"
printf '{"name":"agentbarn-messaging","type":"module","openclaw":{"extensions":["./index.js"]}}' > "$MESSAGE_PLUGIN_DIR/package.json"
printf '{"id":"agentbarn-messaging","name":"Agent Barn messaging","configSchema":{"type":"object","additionalProperties":false,"properties":{}}}' > "$MESSAGE_PLUGIN_DIR/openclaw.plugin.json"
export AGENTBARN_MESSAGE_SPOOL=/home/node/.openclaw/agentbarn-messages.sqlite3
python3 /app/config/agentbarn_message.py drain &
exec openclaw gateway --allow-unconfigured
