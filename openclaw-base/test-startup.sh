#!/bin/sh
set -eu
image="${1:?usage: test-startup.sh IMAGE}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
scripts="$repo_root/api/domains/agents/scripts/openclaw"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The overlay is the builder's real output, so the assertions below track what
# Agent Barn actually ships rather than a copy of it.
(cd "$repo_root/api" && PYTHONPATH="$repo_root" uv run --frozen python -c '
import json
from api.domains.agents.builders import build_openclaw_gateway_config
print(json.dumps(build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")))
') > "$work/openclaw-config-overlay.json"
cp "$scripts/init-openclaw.js" "$scripts/legacy-workspace-migration.sh" "$work/"
chmod -R a+rX "$work"

run() {
    docker run --rm --network none -v "$work:/app/config:ro" --entrypoint sh "$image" -c "$1"
}

echo 'legacy PVC: doctor migrates every known marker and exits 0'
run '
S=/home/node/.openclaw
W=$S/workspace
mkdir -p "$W/.openclaw" "$S/workspace-attestations"
setup="{\"version\":1,\"bootstrapSeededAt\":\"2026-09-01T00:00:00.000Z\",\"setupCompletedAt\":\"2026-09-01T00:00:00.000Z\"}"
attestation="openclaw-workspace-attestation:v1\n2026-09-01T00:00:00.000Z\n"
echo "$setup" > "$W/openclaw-workspace-state.json"
echo "$setup" > "$W/.openclaw/workspace-state.json"
printf "$attestation" > "$S/workspace.attested"
key="$(printf %s "$W" | sha256sum | cut -d" " -f1)"
printf "$attestation" > "$S/workspace-attestations/$key.attested"
sh /app/config/legacy-workspace-migration.sh >/dev/null
for marker in "$W/openclaw-workspace-state.json" "$W/.openclaw/workspace-state.json" \
              "$S/workspace.attested" "$S/workspace-attestations/$key.attested"; do
    [ ! -e "$marker" ] || { echo "marker survived migration: $marker"; exit 1; }
done
'

echo 'clean PVC: doctor must not run'
run '
mkdir -p /tmp/bin
printf "#!/bin/sh\ntouch /tmp/doctor-ran\n" > /tmp/bin/openclaw
chmod +x /tmp/bin/openclaw
PATH=/tmp/bin:$PATH sh /app/config/legacy-workspace-migration.sh
[ ! -e /tmp/doctor-ran ] || { echo "doctor ran on a clean workspace"; exit 1; }
'

echo 'stale PVC heartbeat: init replaces it, config validates, doctor keeps the monitor disabled'
run '
S=/home/node/.openclaw
mkdir -p "$S"
echo "{\"agents\":{\"defaults\":{\"heartbeat\":{\"every\":\"30m\",\"prompt\":\"stale\"}}}}" > "$S/openclaw.json"
node /app/config/init-openclaw.js >/dev/null
node -e "
const cfg = require(process.env.HOME + \"/.openclaw/openclaw.json\");
for (const dir of cfg.plugins.load.paths) require(\"fs\").mkdirSync(dir, {recursive: true});
"
openclaw config validate >/dev/null
[ "$(openclaw config get agents.defaults.heartbeat.prompt 2>/dev/null)" = "" ] || { echo "stale heartbeat keys survived init"; exit 1; }
[ "$(openclaw config get session.dmScope 2>/dev/null)" = "per-channel-peer" ] || { echo "direct messages are not isolated per sender"; exit 1; }
openclaw doctor --fix --non-interactive >/dev/null 2>&1
enabled="$(node --no-warnings -e "
const {DatabaseSync} = require(\"node:sqlite\");
const db = new DatabaseSync(process.env.HOME + \"/.openclaw/state/openclaw.sqlite\", {readOnly: true});
const rows = db.prepare(\"select enabled from cron_jobs where declaration_key = \x27heartbeat:main\x27\").all();
console.log(rows.map((r) => r.enabled).join(\",\"));
")"
[ "$enabled" = 0 ] || { echo "heartbeat monitor enabled=[$enabled], expected 0"; exit 1; }
'

echo 'All OpenClaw startup tests passed'
