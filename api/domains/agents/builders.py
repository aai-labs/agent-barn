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
const PREINSTALLED_NPM_DIR = '/opt/openclaw-preinstalled/npm';
const RUNTIME_NPM_DIR = path.join(HOME, '.openclaw', 'npm');
const PREINSTALLED_NODE_MODULES_DIR = path.join(PREINSTALLED_NPM_DIR, 'node_modules');
const PREINSTALLED_MSTEAMS_DIR = path.join(PREINSTALLED_NODE_MODULES_DIR, '@openclaw', 'msteams');
const RUNTIME_NODE_MODULES_DIR = path.join(RUNTIME_NPM_DIR, 'node_modules');

// These paths are replaced wholesale from the overlay rather than deep-merged,
// so that removals (e.g. removing a channel or DM user) take effect on restart.
const REPLACE_PATHS = [
  ['channels', 'slack', 'channels'],
  ['channels', 'slack', 'allowFrom'],
  ['channels', 'msteams', 'allowFrom'],
];

function getPath(obj, parts) {
  return parts.reduce((cur, key) => (cur && typeof cur === 'object' ? cur[key] : undefined), obj);
}

function setPath(obj, parts, value) {
  const last = parts[parts.length - 1];
  const parent = parts.slice(0, -1).reduce((cur, key) => {
    if (!cur[key] || typeof cur[key] !== 'object') cur[key] = {};
    return cur[key];
  }, obj);
  parent[last] = value;
}

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

function isPathInside(child, parent) {
  const relative = path.relative(parent, child);
  return relative === '' || (!!relative && !relative.startsWith('..') && !path.isAbsolute(relative));
}

function realpathOrResolved(filePath) {
  try { return fs.realpathSync(filePath); }
  catch { return path.resolve(filePath); }
}

function restorePreinstalledMsteamsPlugin(overlay) {
  if (getPath(overlay, ['channels', 'msteams', 'enabled']) !== true) return;
  if (!fs.existsSync(PREINSTALLED_MSTEAMS_DIR)) {
    console.log('[init-openclaw] Preinstalled msteams plugin missing, skipping restore');
    return;
  }

  const sourceReal = realpathOrResolved(PREINSTALLED_NODE_MODULES_DIR);
  const destReal = realpathOrResolved(RUNTIME_NODE_MODULES_DIR);
  if (isPathInside(destReal, sourceReal) || isPathInside(sourceReal, destReal)) {
    console.log('[init-openclaw] Skipping msteams restore: source/destination overlap');
    return;
  }

  if (fs.existsSync(RUNTIME_NPM_DIR) && fs.lstatSync(RUNTIME_NPM_DIR).isSymbolicLink()) {
    console.log('[init-openclaw] Skipping msteams restore: runtime npm path is a symlink');
    return;
  }

  fs.mkdirSync(RUNTIME_NPM_DIR, { recursive: true });
  for (const metadataFile of ['package.json', 'package-lock.json']) {
    const sourceFile = path.join(PREINSTALLED_NPM_DIR, metadataFile);
    if (fs.existsSync(sourceFile)) {
      fs.copyFileSync(sourceFile, path.join(RUNTIME_NPM_DIR, metadataFile));
    }
  }

  fs.mkdirSync(RUNTIME_NODE_MODULES_DIR, { recursive: true });
  fs.cpSync(PREINSTALLED_NODE_MODULES_DIR, RUNTIME_NODE_MODULES_DIR, { recursive: true, force: true });
  console.log('[init-openclaw] Restored preinstalled Microsoft Teams npm plugin');
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

restorePreinstalledMsteamsPlugin(overlay);

let config = {};
try { config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}

const merged = deepMerge(config, overlay);

for (const parts of REPLACE_PATHS) {
  const overlayVal = getPath(overlay, parts);
  if (overlayVal !== undefined) setPath(merged, parts, overlayVal);
}

fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2));
console.log('[init-openclaw] Config merged successfully');

// Overwrite allowFrom credentials so the configured allowlist wins over stale runtime state.
// openclaw writes paired users to <channel>-default-allowFrom.json (wrapped) at runtime; we mirror both here.
for (const [channel, allowFile, defaultAllowFile] of [
  ['slack', 'slack-allowFrom.json', 'slack-default-allowFrom.json'],
  ['msteams', 'msteams-allowFrom.json', 'msteams-default-allowFrom.json'],
]) {
  const af = getPath(overlay, ['channels', channel, 'allowFrom']);
  if (af !== undefined) {
    const credDir = path.join(HOME, '.openclaw', 'credentials');
    fs.mkdirSync(credDir, { recursive: true });
    fs.writeFileSync(path.join(credDir, allowFile), JSON.stringify(af, null, 2));
    fs.writeFileSync(
      path.join(credDir, defaultAllowFile),
      JSON.stringify({ version: 1, allowFrom: af }, null, 2),
    );
    console.log('[init-openclaw] Synced ' + channel + ' allowFrom credentials');
  }
}
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
if [ -f /app/config/aai-cli-setup.sh ]; then
  sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
fi
exec openclaw gateway --allow-unconfigured
"""


def build_openclaw_config_overlay(
    model: str,
    litellm_base_url: str,
    slack_channel_ids: list[str] | None = None,
    slack_dm_user_ids: list[str] | None = None,
    slack_group_policy: str = "open",
    slack_dm_policy: str = "open",
) -> dict:
    provider, _, model_name = model.partition("/")

    channel_ids = slack_channel_ids or []
    dm_user_ids = slack_dm_user_ids or []

    if slack_dm_policy == "off":
        openclaw_dm_policy = "allowlist"
        allow_from = []
        direct_reply_mode = "off"
    elif slack_dm_policy == "open":
        openclaw_dm_policy = "open"
        allow_from = ["*"]
        direct_reply_mode = "all"
    else:
        openclaw_dm_policy = slack_dm_policy
        allow_from = dm_user_ids
        direct_reply_mode = "all"

    channels_config: dict = {
        channel_id: {"enabled": True, "requireMention": False}
        for channel_id in channel_ids
    }

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
                "enabled": True,
                "mode": "socket",
                "webhookPath": "/slack/events",
                "userTokenReadOnly": True,
                "groupPolicy": slack_group_policy,
                "dmPolicy": openclaw_dm_policy,
                "allowFrom": allow_from,
                "replyToModeByChatType": {
                    "direct": direct_reply_mode,
                    "group": "all",
                    "channel": "all",
                },
                "streaming": {
                    "mode": "partial",
                    "nativeTransport": True,
                },
                "channels": channels_config,
            }
        },
        "bindings": [
            {"type": "route", "agentId": "main", "match": {"channel": "slack"}}
        ],
        "tools": {"profile": "full"},
        "memory": {"backend": "builtin"},
        "plugins": {
            "allow": ["memory-core", "active-memory"],
            "slots": {"memory": "memory-core"},
            "entries": {
                "memory-core": {"enabled": True},
                "active-memory": {
                    "enabled": True,
                    "config": {
                        "agents": ["main"],
                        "allowedChatTypes": ["direct", "group", "channel"],
                        "modelFallbackPolicy": "default-remote",
                        "queryMode": "recent",
                        "promptStyle": "balanced",
                        "timeoutMs": 15000,
                        "maxSummaryChars": 220,
                        "persistTranscripts": False,
                        "logging": True,
                    },
                },
            },
        },
    }


def build_openclaw_config_overlay_teams(
    model: str,
    litellm_base_url: str,
) -> dict:
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
            "msteams": {
                "enabled": True,
                "dmPolicy": "open",
                "allowFrom": ["*"],
                "groupPolicy": "open",
                "streaming": {"mode": "off"},
                "webhook": {"port": 3978, "path": "/api/messages"},
            }
        },
        "bindings": [
            {"type": "route", "agentId": "main", "match": {"channel": "msteams"}}
        ],
        "tools": {"profile": "full"},
        "memory": {"backend": "builtin"},
        "plugins": {
            "allow": ["memory-core", "active-memory"],
            "slots": {"memory": "memory-core"},
            "entries": {
                "memory-core": {"enabled": True},
                "active-memory": {
                    "enabled": True,
                    "config": {
                        "agents": ["main"],
                        "allowedChatTypes": ["direct", "group", "channel"],
                        "modelFallbackPolicy": "default-remote",
                        "queryMode": "recent",
                        "promptStyle": "balanced",
                        "timeoutMs": 15000,
                        "maxSummaryChars": 220,
                        "persistTranscripts": False,
                        "logging": True,
                    },
                },
            },
        },
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
    aai_cli_config_toml: str | None = None,
    aai_cli_setup_sh: str | None = None,
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
    if aai_cli_config_toml is not None:
        data["aai-cli-config.toml"] = aai_cli_config_toml
    if aai_cli_setup_sh is not None:
        data["aai-cli-setup.sh"] = aai_cli_setup_sh
    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        data=data,
    )


def build_secret_slack(
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


def build_secret_teams(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    msteams_app_id: str,
    msteams_app_password: str,
    msteams_tenant_id: str,
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
            "MSTEAMS_APP_ID": msteams_app_id,
            "MSTEAMS_APP_PASSWORD": msteams_app_password,
            "MSTEAMS_TENANT_ID": msteams_tenant_id,
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
    include_webhook_port: bool = False,
) -> client.V1Service:
    ports = [
        client.V1ServicePort(port=80, target_port=8080, name="gateway"),
        client.V1ServicePort(port=8081, target_port=8081, name="healthz"),
    ]
    if include_webhook_port:
        ports.append(client.V1ServicePort(port=3978, target_port=3978, name="webhook"))
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1ServiceSpec(
            selector={"app": _resource_name(agent_id)},
            ports=ports,
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
