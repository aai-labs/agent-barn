import json
from pathlib import Path
from uuid import UUID

from kubernetes import client

from .common import _labels, _resource_name

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "openclaw"
_COMMON_SCRIPTS = _SCRIPTS.parent
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"

# OpenClaw's gateway binds this port and its own `openclaw health` CLI resolves
# the same value with no way to override it, so the runtime must not be moved
# off it. The in-pod communications adapter is pointed here to match.
OPENCLAW_GATEWAY_PORT = 18789

INIT_OPENCLAW_JS: str = (_SCRIPTS / "init-openclaw.js").read_text()
HEALTHZ_SERVER_JS: str = (_SCRIPTS / "healthz-server.js").read_text()
START_SH: str = (_SCRIPTS / "start.sh").read_text()
TELEMETRY_PUSH_INDEX_JS: str = (_TELEMETRY_PUSH / "index.js").read_text()
TELEMETRY_PUSH_PACKAGE_JSON: str = (_TELEMETRY_PUSH / "package.json").read_text()
TELEMETRY_PUSH_PLUGIN_JSON: str = (_TELEMETRY_PUSH / "openclaw.plugin.json").read_text()
COMMUNICATIONS_RUNTIME_ADAPTER_PY: str = (_COMMON_SCRIPTS / "communications-runtime-adapter.py").read_text()


def _openclaw_config_core(
    model: str,
    litellm_base_url: str,
    binding_channel: str | None,
    channels: dict,
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
                },
                "memorySearch": {
                    "provider": "none",
                },
            }
        },
        "channels": channels,
        "bindings": (
            [{"type": "route", "agentId": "main", "match": {"channel": binding_channel}}] if binding_channel else []
        ),
        "tools": {
            "profile": "full",
            "exec": {"mode": "full"},
        },
        "memory": {"backend": "builtin"},
        "plugins": {
            "allow": ["memory-core", "active-memory", "telemetry-push"],
            "load": {"paths": ["/home/node/.openclaw/local-plugins/telemetry-push"]},
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
                "telemetry-push": {
                    "enabled": True,
                    "hooks": {"allowConversationAccess": True},
                },
            },
        },
        "gateway": {
            "auth": {"mode": "token"},
            "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
        },
    }


def build_openclaw_gateway_config(model: str, litellm_base_url: str) -> dict:
    return _openclaw_config_core(model, litellm_base_url, binding_channel=None, channels={})


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
    gog_setup_sh: str | None = None,
    skills_json: str | None = None,
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
        data["telemetry-push-index.js"] = TELEMETRY_PUSH_INDEX_JS
        data["telemetry-push-package.json"] = TELEMETRY_PUSH_PACKAGE_JSON
        data["telemetry-push-plugin.json"] = TELEMETRY_PUSH_PLUGIN_JSON
        data["communications-runtime-adapter.py"] = COMMUNICATIONS_RUNTIME_ADAPTER_PY
    if aai_cli_config_toml is not None:
        data["aai-cli-config.toml"] = aai_cli_config_toml
    if aai_cli_setup_sh is not None:
        data["aai-cli-setup.sh"] = aai_cli_setup_sh
    if gog_setup_sh is not None:
        data["gog-setup.sh"] = gog_setup_sh
    if skills_json is not None:
        data["skills.json"] = skills_json
    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        data=data,
    )


def build_secret_runtime(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    *,
    runtime_api_key: str,
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
            "OPENCLAW_GATEWAY_TOKEN": runtime_api_key,
            "RUNTIME_API_KEY": runtime_api_key,
            "RUNTIME_API_URL": f"http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}",
            "RUNTIME_MODEL": "openclaw/default",
            "AGENT_RUNTIME_KIND": "openclaw",
            "LITELLM_API_KEY": litellm_api_key,
            "LITELLM_BASE_URL": litellm_base_url,
        },
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
                        [client.V1LocalObjectReference(name=image_pull_secret)] if image_pull_secret else None
                    ),
                    init_containers=[
                        client.V1Container(
                            name="fix-pvc-owner",
                            image=image,
                            command=["chown", "1000:1000", "/home/node/.openclaw"],
                            security_context=client.V1SecurityContext(
                                run_as_user=0,
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/home/node/.openclaw",
                                ),
                            ],
                        ),
                    ],
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
                            env_from=[client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=name))],
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
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=name),
                        ),
                    ],
                ),
            ),
        ),
    )
