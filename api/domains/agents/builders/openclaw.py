import json
from pathlib import Path
from uuid import UUID

from kubernetes import client

from .common import _labels, _resource_name

# Explicit so agents stop inheriting the namespace LimitRange default of
# 512Mi request / 2Gi limit. requests.memory is the binding quota axis
# (20Gi hard), so the request sets how many agents fit; the 1Gi limit halves
# limits.memory consumption and caps V8, which sizes its heap at ~51% of the
# cgroup limit -- a 2Gi limit invites a 1Gi heap with no leak involved.
AGENT_RESOURCES = client.V1ResourceRequirements(
    requests={"memory": "320Mi", "cpu": "50m"},
    limits={"memory": "1Gi", "cpu": "500m"},
)

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

# The Honcho plugin defaults its sender-to-peer map to ~/.honcho, which is not
# the mounted volume. Held there it is lost on every pod recreation and each
# participant silently becomes a new peer with an empty representation.
OPENCLAW_HONCHO_PEERS_FILE: str = "/home/node/.openclaw/honcho/openclaw-peers.json"

# Generous relative to the ~25s a dialectic recall was measured at, because the
# cost of being too low is silent — recall just never arrives — while the cost of
# being high is only a slower turn when Honcho is genuinely struggling.
HONCHO_RECALL_TIMEOUT_MS: int = 60000


_MEMORY_CORE = "memory-core"
_MEMORY_HONCHO = "openclaw-honcho"

# The Honcho plugin runs an internal memory-search sub-agent, and its turns — the
# sub-agent's own instruction prompt and its bounded "NONE" replies — are captured
# and derived into conclusions as if the user had said them ("owner instructs the
# agent to return NONE…"). On a fresh Agent that scaffolding outnumbers real memory
# before a single genuine message. These patterns drop those turns at capture: the
# plugin merges them with its defaults and `shouldSkipMessage` treats a `/…/`
# entry as a regex tested anywhere in the message. Every phrase is one no human
# types into a chat, so they target the sub-agent without touching real content.
_MEMORY_NOISE_PATTERNS = [
    "/memory search agent/i",
    "/return exactly one of two forms/i",
    "/compact plain-text summary/i",
    "/reply with (?:the word )?NONE/i",
    "/^NONE\\.?$/i",
]


def _memory_plugin(honcho_workspace_id: str | None) -> str:
    """Honcho occupies the single memory slot rather than running beside
    memory-core; two writers over the same semantic state is what the memory
    backend decision exists to remove."""
    return _MEMORY_HONCHO if honcho_workspace_id else _MEMORY_CORE


def _memory_entry(honcho_base_url: str | None, honcho_workspace_id: str | None) -> dict:
    if not honcho_workspace_id:
        return {_MEMORY_CORE: {"enabled": True}}
    return {
        _MEMORY_HONCHO: {
            "enabled": True,
            "config": {
                "baseUrl": honcho_base_url,
                "workspaceId": honcho_workspace_id,
                # Merged with the plugin's own defaults; drops the memory-search
                # sub-agent's turns before they are ever stored (see above).
                "noisePatterns": _MEMORY_NOISE_PATTERNS,
            },
            "hooks": {
                # Without this the runtime blocks the plugin's `agent_end` hook, so
                # no conversation is ever captured and memory stays silently empty.
                # The plugin writes the flag itself and asks for a restart, which
                # means a first run captures nothing unless it is set here up front.
                "allowConversationAccess": True,
                # Recall runs a dialectic query on `before_prompt_build`, which is
                # an LLM call with its own tool loop — measured at ~25s against a
                # real workspace. The runtime's 15s default kills it every turn, so
                # capture works while recall silently never lands.
                "timeoutMs": HONCHO_RECALL_TIMEOUT_MS,
            },
        }
    }


def _openclaw_config_core(
    model: str,
    litellm_base_url: str,
    binding_channel: str | None,
    channels: dict,
    honcho_base_url: str | None = None,
    honcho_workspace_id: str | None = None,
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
        # "builtin" is the file-backed store; "qmd" is the plugin-backed one, and the
        # runtime accepts nothing else (it reports `Invalid input (allowed: "builtin",
        # "qmd")` on anything third). The plugin slot decides which is actually used
        # either way — an Agent with Honcho in the slot runs on Honcho even with
        # "builtin" written here, verified against a live pod — but leaving it saying
        # "builtin" makes the config claim file memory while Honcho holds the data,
        # which is the first place anyone looks when memory seems wrong.
        "memory": {"backend": "qmd" if honcho_workspace_id else "builtin"},
        "plugins": {
            # memory-core stays in `allow` even when Honcho holds the slot: it is
            # not active without an entry, but start.sh needs it permitted to fall
            # back to when the plugin is missing, rather than leaving the Agent
            # with no memory backend at all.
            "allow": [_memory_plugin(honcho_workspace_id), _MEMORY_CORE, "active-memory", "telemetry-push"]
            if honcho_workspace_id
            else [_MEMORY_CORE, "active-memory", "telemetry-push"],
            "load": {"paths": ["/home/node/.openclaw/local-plugins/telemetry-push"]},
            "slots": {"memory": _memory_plugin(honcho_workspace_id)},
            "entries": {
                **_memory_entry(honcho_base_url, honcho_workspace_id),
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


def build_openclaw_gateway_config(
    model: str,
    litellm_base_url: str,
    *,
    honcho_base_url: str | None = None,
    honcho_workspace_id: str | None = None,
) -> dict:
    return _openclaw_config_core(
        model,
        litellm_base_url,
        binding_channel=None,
        channels={},
        honcho_base_url=honcho_base_url,
        honcho_workspace_id=honcho_workspace_id,
    )


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
    labels = _labels(agent_id, org_id, runtime="openclaw")

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            # replicas=1 backed by a ReadWriteOnce PVC: RollingUpdate's surge wants
            # a second pod, which doubles the agent's memory and then deadlocks
            # waiting for a volume the outgoing pod still holds.
            strategy=client.V1DeploymentStrategy(type="Recreate"),
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
                            resources=AGENT_RESOURCES,
                            readiness_probe=client.V1Probe(
                                http_get=client.V1HTTPGetAction(
                                    path="/ready",
                                    port=8081,
                                ),
                                initial_delay_seconds=30,
                                period_seconds=15,
                                failure_threshold=6,
                            ),
                            env=[
                                client.V1EnvVar(
                                    name="OPENCLAW_HONCHO_PEERS_FILE",
                                    value=OPENCLAW_HONCHO_PEERS_FILE,
                                ),
                            ],
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
