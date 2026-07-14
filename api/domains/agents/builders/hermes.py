from pathlib import Path
from uuid import UUID

import yaml
from kubernetes import client

from .common import _labels, _resource_name

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "hermes"
_DENY_DMS = _SCRIPTS / "plugins" / "slack-deny-dms"
_CHANNEL_ALLOWLIST = _SCRIPTS / "plugins" / "slack-channel-allowlist"
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"
_NO_HOME_CHANNEL = "C0000000000"

HERMES_BOOTLOADER_FOOTER: str = (_SCRIPTS / "bootloader-footer.md").read_text()
HERMES_HEALTHZ_PY: str = (_SCRIPTS / "healthz-server.py").read_text()
HERMES_START_SH: str = (_SCRIPTS / "start.sh").read_text()
SLACK_DENY_DMS_PLUGIN_YAML: str = (_DENY_DMS / "plugin.yaml").read_text()
SLACK_DENY_DMS_PLUGIN_INIT: str = (_DENY_DMS / "__init__.py").read_text()
SLACK_CHANNEL_ALLOWLIST_PLUGIN_YAML: str = (
    _CHANNEL_ALLOWLIST / "plugin.yaml"
).read_text()
SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT: str = (
    _CHANNEL_ALLOWLIST / "__init__.py"
).read_text()
TELEMETRY_PUSH_PLUGIN_YAML: str = (_TELEMETRY_PUSH / "plugin.yaml").read_text()
TELEMETRY_PUSH_PLUGIN_INIT: str = (_TELEMETRY_PUSH / "__init__.py").read_text()


_HERMES_APPROVAL_MODE = {"manual": "manual", "auto": "smart", "off": "off"}


def build_hermes_config(
    model: str,
    litellm_base_url: str,
    dm_policy: str = "off",
    group_policy: str = "allowlist",
    verbose_mode: bool = True,
    approval_mode: str = "auto",
) -> dict:
    _, sep, model_name = model.partition("/")
    if not sep:
        model_name = model
    # Slack access is gated by two plugins, each dropped entirely when its policy
    # is "open" so the policy is truly unrestricted regardless of any retained
    # channel/user lists (the lists persist in config so switching back to
    # allowlist restores them):
    #   - slack-channel-allowlist scopes channel replies to SLACK_CHANNEL_IDS
    #   - slack-deny-dms scopes DMs to SLACK_DM_ALLOWED_USERS
    # SLACK_ALLOW_ALL_USERS already authorizes every user at the gateway, so
    # dropping a hook opens that surface up.
    enabled_plugins: list[str] = ["telemetry-push"]
    if group_policy != "open":
        enabled_plugins.append("slack-channel-allowlist")
    if dm_policy != "open":
        enabled_plugins.append("slack-deny-dms")
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
            "platforms": {
                "slack": {
                    "tool_progress": "off",
                    "interim_assistant_messages": verbose_mode,
                    "busy_ack_detail": False,
                },
            },
        },
        "group_sessions_per_user": False,
        "slack": {
            "reply_in_thread": True,
            "broadcast_reply": False,
            "require_mention": True,
            "strict_mention": False,
            "unauthorized_dm_behavior": "ignore",
        },
        "plugins": {
            "enabled": enabled_plugins,
        },
        "approvals": {
            "mode": _HERMES_APPROVAL_MODE.get(approval_mode, "smart"),
        },
    }


def build_hermes_config_telegram(
    model: str,
    litellm_base_url: str,
    dm_policy: str = "off",
    group_policy: str = "allowlist",
    allowed_user_ids: list[str] | None = None,
    allowed_chat_ids: list[str] | None = None,
    approval_mode: str = "auto",
) -> dict:
    _, sep, model_name = model.partition("/")
    if not sep:
        model_name = model

    if dm_policy == "open":
        allow_from: list[str] = ["*"]
    elif dm_policy == "allowlist":
        allow_from = list(allowed_user_ids or [])
    else:
        allow_from = []

    config: dict = {
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
            "platforms": {
                "telegram": {
                    "tool_progress": "off",
                },
            },
        },
        "group_sessions_per_user": False,
        "allow_from": allow_from,
        "plugins": {
            "enabled": ["telemetry-push"],
        },
        "approvals": {
            "mode": _HERMES_APPROVAL_MODE.get(approval_mode, "smart"),
        },
    }

    if group_policy == "open":
        config["guest_mode"] = True
    else:
        config["guest_mode"] = False
        config["group_allowed_chats"] = list(allowed_chat_ids or [])

    return config


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
    skills_json: str | None = None,
    platform: str = "slack",
) -> client.V1ConfigMap:
    data: dict[str, str] = {
        "SOUL.md": soul_md + HERMES_BOOTLOADER_FOOTER,
        "IDENTITY.md": identity_md,
        "USER.md": user_md,
        "TOOLS.md": tools_md,
        "AGENTS.md": agents_md,
        "BOOT.md": boot_md,
        "HEARTBEAT.md": heartbeat_md,
        "hermes-config.yaml": yaml.dump(
            hermes_config, default_flow_style=False, sort_keys=False
        ),
        "telemetry-push-plugin.yaml": TELEMETRY_PUSH_PLUGIN_YAML,
        "telemetry-push-init.py": TELEMETRY_PUSH_PLUGIN_INIT,
        "healthz-server.py": HERMES_HEALTHZ_PY,
        "start.sh": HERMES_START_SH,
    }
    if platform == "slack":
        data["slack-deny-dms-plugin.yaml"] = SLACK_DENY_DMS_PLUGIN_YAML
        data["slack-deny-dms-init.py"] = SLACK_DENY_DMS_PLUGIN_INIT
        data["slack-channel-allowlist-plugin.yaml"] = SLACK_CHANNEL_ALLOWLIST_PLUGIN_YAML
        data["slack-channel-allowlist-init.py"] = SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT
    if aai_cli_config_toml is not None:
        data["aai-cli-config.toml"] = aai_cli_config_toml
    if aai_cli_setup_sh is not None:
        data["aai-cli-setup.sh"] = aai_cli_setup_sh
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


def build_secret_hermes_slack(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    agent_name: str,
    slack_bot_token: str,
    slack_app_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
    api_server_key: str,
    channel_ids: list[str],
    dm_user_ids: list[str],
    dm_policy: str = "off",
) -> client.V1Secret:
    # Only an explicit allowlist seeds SLACK_DM_ALLOWED_USERS. "off" denies every
    # DM (empty allowlist behind the deny plugin); "open" drops the deny plugin,
    # so the value is unused there. This keeps a stale user list from leaking DM
    # access when the policy is switched away from allowlist.
    allowed_dm_users = dm_user_ids if dm_policy == "allowlist" else []
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data={
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_APP_TOKEN": slack_app_token,
            "OPENAI_API_KEY": litellm_api_key,
            "OPENAI_BASE_URL": litellm_base_url,
            "OPENROUTER_BASE_URL": litellm_base_url,
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "0.0.0.0",
            "API_SERVER_PORT": "8642",
            "API_SERVER_KEY": api_server_key,
            "API_SERVER_MODEL_NAME": agent_name,
            "GATEWAY_ALLOW_ALL_USERS": "true",
            "SLACK_ALLOW_ALL_USERS": "true",
            "SLACK_HOME_CHANNEL": channel_ids[0] if channel_ids else _NO_HOME_CHANNEL,
            "SLACK_CHANNEL_IDS": ",".join(channel_ids),
            "SLACK_DM_ALLOWED_USERS": ",".join(allowed_dm_users),
            "AGENT_PLATFORM": "slack",
        },
    )


def build_secret_hermes_telegram(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    agent_name: str,
    telegram_bot_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
    api_server_key: str,
) -> client.V1Secret:
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data={
            "TELEGRAM_BOT_TOKEN": telegram_bot_token,
            "OPENAI_API_KEY": litellm_api_key,
            "OPENAI_BASE_URL": litellm_base_url,
            "OPENROUTER_BASE_URL": litellm_base_url,
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "0.0.0.0",
            "API_SERVER_PORT": "8642",
            "API_SERVER_KEY": api_server_key,
            "API_SERVER_MODEL_NAME": agent_name,
            "GATEWAY_ALLOW_ALL_USERS": "true",
            "AGENT_PLATFORM": "telegram",
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
                                    mount_path="/opt/data",
                                ),
                                client.V1VolumeMount(
                                    name="workspace",
                                    mount_path="/workspace",
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
                        client.V1Volume(
                            name="workspace",
                            empty_dir=client.V1EmptyDirVolumeSource(),
                        ),
                    ],
                ),
            ),
        ),
    )
