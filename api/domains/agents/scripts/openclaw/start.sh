#!/bin/sh
set -e
node /app/config/healthz-server.js &
node /app/config/init-openclaw.js
if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi
exec openclaw gateway --allow-unconfigured
