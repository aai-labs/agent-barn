#!/bin/sh
set -e
node /app/config/healthz-server.js &
node /app/config/init-openclaw.js
exec openclaw gateway --allow-unconfigured
