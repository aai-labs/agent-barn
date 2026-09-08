#!/bin/sh
set -e
node /app/config/healthz-server.js &
python3 /app/config/communications-runtime-adapter.py &
# Honcho's plugin has to be installed before any config names it. `openclaw
# plugins install` refuses to run against an invalid config, and a config whose
# memory slot points at a not-yet-installed plugin is invalid — which also takes
# every other plugin install below down with it. The config persists on the PVC,
# so a previous run's copy still names the plugin on restart; strip the reference
# first, install, then let init-openclaw.js merge the overlay back and restore it.
if grep -q '"openclaw-honcho"' /app/config/openclaw-config-overlay.json 2>/dev/null; then
  mkdir -p /home/node/.openclaw/honcho
  node -e '
    const fs = require("fs");
    const p = "/home/node/.openclaw/openclaw.json";
    if (!fs.existsSync(p)) process.exit(0);
    try {
      const c = JSON.parse(fs.readFileSync(p, "utf8"));
      const pl = c.plugins;
      if (!pl) process.exit(0);
      if (pl.slots && pl.slots.memory === "openclaw-honcho") delete pl.slots.memory;
      if (pl.entries) delete pl.entries["openclaw-honcho"];
      if (Array.isArray(pl.allow)) pl.allow = pl.allow.filter((n) => n !== "openclaw-honcho");
      fs.writeFileSync(p, JSON.stringify(c, null, 2));
    } catch (e) {
      console.log("[start] could not strip honcho refs before install: " + e.message);
    }
  ' || true
  install_out=$(openclaw plugins install @honcho-ai/openclaw-honcho@1.5.5 2>&1) || true
  # The plugin lives on the PVC, so every restart after the first re-reports it as
  # already present. That is the healthy steady state, not a failure.
  if echo "$install_out" | grep -q "plugin already exists"; then
    echo "[start] honcho plugin already installed"
  elif echo "$install_out" | grep -qiE "error|failed"; then
    echo "[start] honcho plugin install failed: $(echo "$install_out" | tail -2)"
  fi
fi

node /app/config/init-openclaw.js

# init has just written a config whose memory slot names the Honcho plugin. If the
# plugin is not actually installed, that config is invalid and the Agent ends up
# with no memory backend at all — worse than the file-backed one it replaced. Fall
# back rather than start an Agent that silently cannot remember anything.
if grep -q '"openclaw-honcho"' /app/config/openclaw-config-overlay.json 2>/dev/null; then
  if ! ls -d /home/node/.openclaw/npm/projects/honcho-ai-openclaw-honcho-*/node_modules/@honcho-ai/openclaw-honcho >/dev/null 2>&1; then
    echo "[start] honcho plugin unavailable — falling back to file-backed memory-core"
    node -e '
      const fs = require("fs");
      const p = "/home/node/.openclaw/openclaw.json";
      try {
        const c = JSON.parse(fs.readFileSync(p, "utf8"));
        c.plugins = c.plugins || {};
        c.plugins.slots = c.plugins.slots || {};
        c.plugins.entries = c.plugins.entries || {};
        c.plugins.slots.memory = "memory-core";
        c.plugins.entries["memory-core"] = { enabled: true };
        delete c.plugins.entries["openclaw-honcho"];
        if (Array.isArray(c.plugins.allow)) {
          c.plugins.allow = c.plugins.allow.filter((n) => n !== "openclaw-honcho");
        }
        fs.writeFileSync(p, JSON.stringify(c, null, 2));
      } catch (e) {
        console.log("[start] could not fall back to memory-core: " + e.message);
      }
    ' || true
  fi
fi

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
exec openclaw gateway --allow-unconfigured
