set -eu
state=/home/node/.openclaw
mkdir -p "$state/local-plugins"
cp -r /plugins/telemetry-push /plugins/agentbarn-observer /plugins/agentbarn-bot-env /plugins/agentbarn-tasks /plugins/agentbarn-listen-in "$state/local-plugins/"
chmod -R go-w "$state/local-plugins"
cp /scripts/init-openclaw.js /scripts/bot-setup.py /app/config/
export TELEGRAM_BOT_TOKEN=1:parent LITELLM_API_KEY=parent MEMORY_URL=http://127.0.0.1:9 MEMORY_API_KEY=parent

snapshot() {
  openclaw config validate --json > "/out/$1-validate.json" 2>/dev/null || true
  openclaw agents list --json > "/out/$1-agents.json" 2>/dev/null || true
  openclaw secrets audit --json > "/out/$1-audit.json" 2>/dev/null || true
  cp "$state/openclaw.json" "/out/$1-config.json"
}

cp /in/single.json /app/config/openclaw-config-overlay.json
node /app/config/init-openclaw.js > /dev/null
snapshot alone

cp /in/multi.json /app/config/openclaw-config-overlay.json
cp /in/bots.json /app/config/bots.json
node /app/config/init-openclaw.js > /dev/null
python3 /app/config/bot-setup.py > /out/bots-setup.log
snapshot bots

cp /in/single.json /app/config/openclaw-config-overlay.json
rm /app/config/bots.json
node /app/config/init-openclaw.js > /dev/null
snapshot after
