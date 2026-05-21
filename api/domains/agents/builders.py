import json
from uuid import UUID

from kubernetes import client


def _resource_name(agent_id: UUID) -> str:
    return f"agent-{agent_id}"


def _labels(agent_id: UUID, org_id: UUID) -> dict[str, str]:
    return {"app": _resource_name(agent_id), "org-id": str(org_id)}


INIT_OPENCLAW_JS = """\
const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || '/home/node';
const TEMPLATE_DIR = '/app/config';
const WORKSPACE_DIR = path.join(HOME, '.openclaw', 'workspace');
const OVERLAY_PATH = path.join(TEMPLATE_DIR, 'openclaw-config-overlay.json');
const CONFIG_PATH = path.join(HOME, '.openclaw', 'openclaw.json');

function deepMerge(base, overlay) {
  const result = Object.assign({}, base);
  for (const [key, val] of Object.entries(overlay)) {
    result[key] = (val && typeof val === 'object' && !Array.isArray(val)
      && result[key] && typeof result[key] === 'object' && !Array.isArray(result[key]))
      ? deepMerge(result[key], val)
      : val;
  }
  return result;
}

fs.mkdirSync(WORKSPACE_DIR, { recursive: true });
for (const file of fs.readdirSync(TEMPLATE_DIR)) {
  if (!file.endsWith('.md')) continue;
  fs.copyFileSync(path.join(TEMPLATE_DIR, file), path.join(WORKSPACE_DIR, file));
  console.log(`[init-openclaw] Copied workspace/${file}`);
}

let overlay;
try { overlay = JSON.parse(fs.readFileSync(OVERLAY_PATH, 'utf8')); }
catch { console.log('[init-openclaw] No overlay found, skipping'); process.exit(0); }

let config = {};
try { config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}

const merged = deepMerge(config, overlay);
fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2));
console.log('[init-openclaw] Config merged successfully');
"""

HEALTHZ_SERVER_JS = """\
const http = require('http');
const { execFile } = require('child_process');

const PORT = 8081;
const CACHE_TTL_MS = 10_000;

let cache = null;
let refreshing = false;

function refresh() {
  if (refreshing) return;
  refreshing = true;
  execFile('openclaw', ['health', '--json'], { timeout: 15_000 }, (err, stdout) => {
    refreshing = false;
    if (err) {
      cache = { ok: false, everConnected: false, reason: err.message };
      return;
    }
    try {
      const d = JSON.parse(stdout);
      const order = d.channelOrder || [];
      if (!order.length) { cache = { ok: false, everConnected: false, reason: 'no channels configured' }; return; }
      for (const ch of order) {
        const channel = d.channels[ch];
        if (channel?.healthState !== 'healthy') {
          const everConnected = typeof channel?.lastConnectedAt === 'number';
          const hasError = channel?.lastError != null;
          cache = { ok: false, everConnected: everConnected || hasError, reason: channel?.lastError || 'channel ' + ch + ' not connected' };
          return;
        }
      }
      cache = { ok: true };
    } catch {
      cache = { ok: false, everConnected: false, reason: 'failed to parse health output' };
    }
  });
}

refresh();
setInterval(refresh, CACHE_TTL_MS);

const server = http.createServer((req, res) => {
  if (req.method !== 'GET') { res.writeHead(404); res.end(); return; }

  if (req.url === '/ready') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ready: true }));
    return;
  }

  if (req.url === '/healthz') {
    if (!cache) {
      res.writeHead(503, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'starting' }));
      return;
    }
    if (cache.ok) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
      return;
    }
    if (cache.everConnected) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'error', reason: cache.reason }));
      return;
    }
    res.writeHead(503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'starting', reason: cache.reason }));
    return;
  }

  res.writeHead(404);
  res.end();
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));

server.listen(PORT, () => console.log('[healthz] listening on :' + PORT));
"""

START_SH = """\
#!/bin/sh
set -e
node /app/config/healthz-server.js &
node /app/config/init-openclaw.js
exec openclaw gateway --allow-unconfigured
"""


def build_openclaw_config_overlay(model: str, litellm_base_url: str) -> dict:
    provider, _, model_name = model.partition("/")
    return {
        "models": {
            "providers": {
                provider: {
                    "baseUrl": litellm_base_url,
                    "models": [{"id": model_name, "name": model_name}],
                }
            }
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": model,
                }
            }
        },
        "channels": {
            "slack": {
                "mode": "socket",
                "webhookPath": "/slack/events",
                "userTokenReadOnly": True,
                "groupPolicy": "open",
                "dmPolicy": "open",
                "allowFrom": ["*"],
            }
        },
        "bindings": [
            {"type": "route", "agentId": "main", "match": {"channel": "slack"}}
        ],
    }


def build_config_map(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    soul_md: str,
    identity_md: str,
    user_md: str,
    tools_md: str,
    agents_md: str,
    boot_md: str,
    bootstrap_md: str,
    heartbeat_md: str,
    openclaw_config_overlay: dict | None = None,
) -> client.V1ConfigMap:
    data = {
        "SOUL.md": soul_md,
        "IDENTITY.md": identity_md,
        "USER.md": user_md,
        "TOOLS.md": tools_md,
        "AGENTS.md": agents_md,
        "BOOT.md": boot_md,
        "BOOTSTRAP.md": bootstrap_md,
        "HEARTBEAT.md": heartbeat_md,
    }
    if openclaw_config_overlay is not None:
        data["openclaw-config-overlay.json"] = json.dumps(openclaw_config_overlay)
        data["init-openclaw.js"] = INIT_OPENCLAW_JS
        data["healthz-server.js"] = HEALTHZ_SERVER_JS
        data["start.sh"] = START_SH
    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        data=data,
    )


def build_secret(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    slack_bot_token: str,
    slack_app_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
) -> client.V1Secret:
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data={
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_APP_TOKEN": slack_app_token,
            "LITELLM_API_KEY": litellm_api_key,
            "LITELLM_BASE_URL": litellm_base_url,
        },
    )


def build_pvc(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
) -> client.V1PersistentVolumeClaim:
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=client.V1ResourceRequirements(
                requests={"storage": "1Gi"},
            ),
        ),
    )


def build_service(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
) -> client.V1Service:
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1ServiceSpec(
            selector={"app": _resource_name(agent_id)},
            ports=[
                client.V1ServicePort(port=80, target_port=8080, name="gateway"),
                client.V1ServicePort(port=8081, target_port=8081, name="healthz"),
            ],
        ),
    )


def build_deployment(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    image: str,
    image_pull_secret: str = "",
) -> client.V1Deployment:
    name = _resource_name(agent_id)
    labels = _labels(agent_id, org_id)

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    image_pull_secrets=(
                        [client.V1LocalObjectReference(name=image_pull_secret)]
                        if image_pull_secret
                        else None
                    ),
                    containers=[
                        client.V1Container(
                            name="agent",
                            image=image,
                            command=["sh", "/app/config/start.sh"],
                            readiness_probe=client.V1Probe(
                                http_get=client.V1HTTPGetAction(
                                    path="/ready",
                                    port=8081,
                                ),
                                initial_delay_seconds=30,
                                period_seconds=15,
                                failure_threshold=6,
                            ),
                            env_from=[
                                client.V1EnvFromSource(
                                    secret_ref=client.V1SecretEnvSource(name=name)
                                )
                            ],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="config",
                                    mount_path="/app/config",
                                ),
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/home/node/.openclaw",
                                ),
                            ],
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="config",
                            config_map=client.V1ConfigMapVolumeSource(name=name),
                        ),
                        client.V1Volume(
                            name="data",
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=name
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )
