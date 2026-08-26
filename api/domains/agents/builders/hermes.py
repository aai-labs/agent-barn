from pathlib import Path
from uuid import UUID

import yaml
from kubernetes import client

from .common import _labels, _resource_name

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "hermes"
_COMMON_SCRIPTS = _SCRIPTS.parent
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"

HERMES_BOOTLOADER_FOOTER: str = (_SCRIPTS / "bootloader-footer.md").read_text()
HERMES_HEALTHZ_PY: str = (_SCRIPTS / "healthz-server.py").read_text()
HERMES_START_SH: str = (_SCRIPTS / "start.sh").read_text()
TELEMETRY_PUSH_PLUGIN_YAML: str = (_TELEMETRY_PUSH / "plugin.yaml").read_text()
TELEMETRY_PUSH_PLUGIN_INIT: str = (_TELEMETRY_PUSH / "__init__.py").read_text()
COMMUNICATIONS_RUNTIME_ADAPTER_PY: str = (_COMMON_SCRIPTS / "communications-runtime-adapter.py").read_text()


_HERMES_APPROVAL_MODE = {"manual": "manual", "auto": "smart", "off": "off"}


def _hermes_config_core(
    model: str,
    litellm_base_url: str,
    enabled_plugins: list[str],
    approval_mode: str = "auto",
) -> dict:
    _, sep, model_name = model.partition("/")
    if not sep:
        model_name = model
    return {
        "toolsets": ["all"],
        "model": {
            "provider": "openrouter",
            "default": model_name,
            "model": model_name,
            "base_url": litellm_base_url,
            "api_mode": "chat_completions",
        },
        "terminal": {
            "backend": "local",
            "cwd": "/workspace",
            "timeout": 120,
        },
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": True,
        },
        "compression": {
            "enabled": False,
        },
        "agent": {
            "max_turns": 50,
        },
        "display": {
            "tool_progress": "all",
            "platforms": {},
        },
        "group_sessions_per_user": False,
        "plugins": {
            "enabled": enabled_plugins,
        },
        "approvals": {
            "mode": _HERMES_APPROVAL_MODE.get(approval_mode, "smart"),
        },
    }


def build_hermes_gateway_config(
    model: str,
    litellm_base_url: str,
    approval_mode: str = "auto",
) -> dict:
    return _hermes_config_core(
        model,
        litellm_base_url,
        enabled_plugins=["telemetry-push"],
        approval_mode=approval_mode,
    )


def build_hermes_config_map(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    soul_md: str,
    identity_md: str,
    user_md: str,
    tools_md: str,
    agents_md: str,
    boot_md: str,
    heartbeat_md: str,
    hermes_config: dict,
    aai_cli_config_toml: str | None = None,
    aai_cli_setup_sh: str | None = None,
    gog_setup_sh: str | None = None,
    skills_json: str | None = None,
) -> client.V1ConfigMap:
    data: dict[str, str] = {
        "SOUL.md": soul_md + HERMES_BOOTLOADER_FOOTER,
        "IDENTITY.md": identity_md,
        "USER.md": user_md,
        "TOOLS.md": tools_md,
        "AGENTS.md": agents_md,
        "BOOT.md": boot_md,
        "HEARTBEAT.md": heartbeat_md,
        "hermes-config.yaml": yaml.dump(hermes_config, default_flow_style=False, sort_keys=False),
        "telemetry-push-plugin.yaml": TELEMETRY_PUSH_PLUGIN_YAML,
        "telemetry-push-init.py": TELEMETRY_PUSH_PLUGIN_INIT,
        "healthz-server.py": HERMES_HEALTHZ_PY,
        "start.sh": HERMES_START_SH,
        "communications-runtime-adapter.py": COMMUNICATIONS_RUNTIME_ADAPTER_PY,
    }
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


def build_secret_hermes_runtime(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    agent_name: str,
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
            "OPENAI_API_KEY": litellm_api_key,
            "OPENAI_BASE_URL": litellm_base_url,
            "OPENROUTER_BASE_URL": litellm_base_url,
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "0.0.0.0",
            "API_SERVER_PORT": "8642",
            "API_SERVER_KEY": runtime_api_key,
            "API_SERVER_MODEL_NAME": agent_name,
            "RUNTIME_API_KEY": runtime_api_key,
            "RUNTIME_API_URL": "http://127.0.0.1:8642",
            "RUNTIME_MODEL": agent_name,
        },
    )


def build_hermes_deployment(
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
                            liveness_probe=client.V1Probe(
                                http_get=client.V1HTTPGetAction(
                                    path="/live",
                                    port=8081,
                                ),
                                initial_delay_seconds=60,
                                period_seconds=60,
                                failure_threshold=5,
                                timeout_seconds=5,
                            ),
                            env=[
                                # The hermes process starts in its install dir
                                # (/opt/hermes) and the runtime user's HOME is
                                # /opt/data (the state dir), so without these the
                                # agent's shell is anchored in the wrong place and
                                # relative writes miss the persistent /workspace.
                                # ocbw sets both alongside terminal.cwd — mirror it.
                                client.V1EnvVar(name="TERMINAL_CWD", value="/workspace"),
                                client.V1EnvVar(name="MESSAGING_CWD", value="/workspace"),
                            ],
                            env_from=[client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=name))],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="config",
                                    mount_path="/app/config",
                                ),
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/opt/data",
                                ),
                                # /workspace is the agent's cwd; back it with the
                                # per-agent PVC so agent-written files survive
                                # restarts (AF-215) — like ocbw's persistent
                                # ./agents/<name>/workspace and OpenClaw's
                                # PVC-nested workspace. subPath keeps it a
                                # sibling of the /opt/data content on one PVC.
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/workspace",
                                    sub_path="workspace",
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
