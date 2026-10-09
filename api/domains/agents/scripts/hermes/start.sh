#!/bin/sh
set -e
python3 /app/config/retire-messaging.py hermes /opt/data
python3 /app/config/healthz-server.py &
python3 /app/config/communications-runtime-adapter.py &
python3 /app/config/agent-trigger-server.py &

mkdir -p /opt/data/plugins/telemetry-push /opt/data/memories /workspace


if [ ! -f /opt/data/memories/USER.md ]; then
    cp /app/config/USER.md /opt/data/memories/USER.md
fi

cp /app/config/SOUL.md /opt/data/SOUL.md
python3 /app/config/config-merge.py /app/config/hermes-config.yaml /opt/data/config.yaml \
    || cp /app/config/hermes-config.yaml /opt/data/config.yaml

# Remove any stale .env from the PVC — all vars are injected via k8s Secret.
# A persisted .env takes precedence over system env and would cause stale
# values (e.g. old home channel) to survive pod restarts.
rm -f /opt/data/.env

python3 /app/config/memory-setup.py
if [ -n "${MEMORY_API_KEY:-}" ]; then
  export HINDSIGHT_API_KEY="$MEMORY_API_KEY"
  python3 /app/config/memory-gateway-ready.py || true
fi

cp /app/config/telemetry-push-plugin.yaml /opt/data/plugins/telemetry-push/plugin.yaml
cp /app/config/telemetry-push-init.py /opt/data/plugins/telemetry-push/__init__.py
# Enabled only for native gateway Connections via plugins.enabled.
mkdir -p /opt/data/plugins/agentbarn-observer
cp /app/config/agentbarn-observer-plugin.yaml /opt/data/plugins/agentbarn-observer/plugin.yaml
cp /app/config/agentbarn-observer-init.py /opt/data/plugins/agentbarn-observer/__init__.py

for f in IDENTITY.md AGENTS.md TOOLS.md BOOT.md HEARTBEAT.md; do
    cp /app/config/$f /workspace/$f
done

# The gog wrapper installs here when Google Workspace is brokered through the
# credential gateway. Ahead of /usr/local/bin so agent commands resolve it first.
export PATH="/home/hermes/.local/bin:$PATH"

if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || exit $?
fi

if [ -f /app/config/gog-setup.sh ]; then
  sh /app/config/gog-setup.sh || exit $?
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

# Pinned Hermes never runs BOOT.md; OpenClaw bundles a gateway:startup hook for it.
python3 /app/config/boot-run.py &
exec hermes gateway run
