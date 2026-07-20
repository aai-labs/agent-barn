#!/bin/sh
set -e

python3 /app/config/healthz-server.py &

mkdir -p /opt/data/plugins/slack-deny-dms /opt/data/plugins/slack-channel-allowlist /opt/data/plugins/telemetry-push /opt/data/memories /workspace


if [ ! -f /opt/data/memories/USER.md ]; then
    cp /app/config/USER.md /opt/data/memories/USER.md
fi

cp /app/config/SOUL.md /opt/data/SOUL.md
cp /app/config/hermes-config.yaml /opt/data/config.yaml

# Remove any stale .env from the PVC — all vars are injected via k8s Secret.
# A persisted .env takes precedence over system env and would cause stale
# values (e.g. old home channel) to survive pod restarts.
rm -f /opt/data/.env

cp /app/config/slack-deny-dms-plugin.yaml /opt/data/plugins/slack-deny-dms/plugin.yaml
cp /app/config/slack-deny-dms-init.py /opt/data/plugins/slack-deny-dms/__init__.py

cp /app/config/slack-channel-allowlist-plugin.yaml /opt/data/plugins/slack-channel-allowlist/plugin.yaml
cp /app/config/slack-channel-allowlist-init.py /opt/data/plugins/slack-channel-allowlist/__init__.py

cp /app/config/telemetry-push-plugin.yaml /opt/data/plugins/telemetry-push/plugin.yaml
cp /app/config/telemetry-push-init.py /opt/data/plugins/telemetry-push/__init__.py

for f in IDENTITY.md AGENTS.md TOOLS.md BOOT.md HEARTBEAT.md; do
    cp /app/config/$f /workspace/$f
done

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi

# /workspace persists across restarts (PVC). The personality files above are
# overwritten from the configmap every boot, but skills are additive — prune
# them so a skill from a removed integration can't linger from a previous boot.
rm -rf /workspace/skills

if [ -f /app/config/skills.json ]; then
  python3 - <<'PYEOF'
import json, pathlib
manifest = json.loads(open('/app/config/skills.json').read())
skills_dir = pathlib.Path('/workspace/skills')
written = 0
for entry in manifest:
    dest = (skills_dir / entry['path']).resolve()
    if not str(dest).startswith(str(skills_dir.resolve())):
        continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(entry['content'])
    written += 1
print(f'[hermes-start] Wrote {written} skill files')
PYEOF
fi

exec hermes gateway run
