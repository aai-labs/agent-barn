set -eu
state=/home/node/.openclaw
mkdir -p "$state/local-plugins" /tmp/agentbarn-keys
cp -r /plugins/telemetry-push /plugins/agentbarn-observer /plugins/agentbarn-bot-env /plugins/agentbarn-tasks /plugins/agentbarn-listen-in "$state/local-plugins/"
chmod -R go-w "$state/local-plugins"
cp /in/openclaw.json "$state/openclaw.json"
(
  umask 077
  for file in /in/keys/*.json; do
    if [ -f "$file" ]; then cp "$file" /tmp/agentbarn-keys/; fi
  done
)
export TELEGRAM_BOT_TOKEN=1:parent LITELLM_API_KEY=parent MEMORY_URL=http://127.0.0.1:9 MEMORY_API_KEY=parent
openclaw config validate --json > /out/validate.json 2>/out/validate.err || true
openclaw agents list --json --bindings > /out/agents.json 2>/out/agents.err || true
openclaw secrets audit --json > /out/audit.json 2>/out/audit.err || true
