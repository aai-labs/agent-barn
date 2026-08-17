from pathlib import Path
from uuid import UUID

import yaml
from kubernetes import client

from .common import _labels, _resource_name

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "hermes"
_DENY_DMS = _SCRIPTS / "plugins" / "slack-deny-dms"
_CHANNEL_ALLOWLIST = _SCRIPTS / "plugins" / "slack-channel-allowlist"
_TG_DENY_DMS = _SCRIPTS / "plugins" / "telegram-deny-dms"
_TG_CHANNEL_ALLOWLIST = _SCRIPTS / "plugins" / "telegram-channel-allowlist"
_DISCORD_DENY_DMS = _SCRIPTS / "plugins" / "discord-deny-dms"
_DISCORD_GUILD_ALLOWLIST = _SCRIPTS / "plugins" / "discord-guild-allowlist"
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"
_NO_SLACK_HOME_CHANNEL = "C0000000000"
_NO_TELEGRAM_HOME_CHANNEL = "0000000000"
_NO_TELEGRAM_HOME_CHANNEL_NAME = "No Telegram Home Channel"
_NO_DISCORD_HOME_CHANNEL = "000000000000000000"

HERMES_BOOTLOADER_FOOTER: str = (_SCRIPTS / "bootloader-footer.md").read_text()
HERMES_HEALTHZ_PY: str = (_SCRIPTS / "healthz-server.py").read_text()
HERMES_START_SH: str = (_SCRIPTS / "start.sh").read_text()
SLACK_DENY_DMS_PLUGIN_YAML: str = (_DENY_DMS / "plugin.yaml").read_text()
SLACK_DENY_DMS_PLUGIN_INIT: str = (_DENY_DMS / "__init__.py").read_text()
SLACK_CHANNEL_ALLOWLIST_PLUGIN_YAML: str = (_CHANNEL_ALLOWLIST / "plugin.yaml").read_text()
SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT: str = (_CHANNEL_ALLOWLIST / "__init__.py").read_text()
TELEGRAM_DENY_DMS_PLUGIN_YAML: str = (_TG_DENY_DMS / "plugin.yaml").read_text()
TELEGRAM_DENY_DMS_PLUGIN_INIT: str = (_TG_DENY_DMS / "__init__.py").read_text()
TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_YAML: str = (_TG_CHANNEL_ALLOWLIST / "plugin.yaml").read_text()
TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_INIT: str = (_TG_CHANNEL_ALLOWLIST / "__init__.py").read_text()
DISCORD_DENY_DMS_PLUGIN_YAML: str = (_DISCORD_DENY_DMS / "plugin.yaml").read_text()
DISCORD_DENY_DMS_PLUGIN_INIT: str = (_DISCORD_DENY_DMS / "__init__.py").read_text()
DISCORD_GUILD_ALLOWLIST_PLUGIN_YAML: str = (_DISCORD_GUILD_ALLOWLIST / "plugin.yaml").read_text()
DISCORD_GUILD_ALLOWLIST_PLUGIN_INIT: str = (_DISCORD_GUILD_ALLOWLIST / "__init__.py").read_text()
TELEMETRY_PUSH_PLUGIN_YAML: str = (_TELEMETRY_PUSH / "plugin.yaml").read_text()
TELEMETRY_PUSH_PLUGIN_INIT: str = (_TELEMETRY_PUSH / "__init__.py").read_text()


_HERMES_APPROVAL_MODE = {"manual": "manual", "auto": "smart", "off": "off"}


def _hermes_config_core(
    model: str,
    litellm_base_url: str,
    enabled_plugins: list[str],
    display_platforms: dict,
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
            "platforms": display_platforms,
        },
        "group_sessions_per_user": False,
        "plugins": {
            "enabled": enabled_plugins,
        },
        "approvals": {
            "mode": _HERMES_APPROVAL_MODE.get(approval_mode, "smart"),
        },
    }


def build_hermes_config(
    model: str,
    litellm_base_url: str,
    dm_policy: str = "off",
    group_policy: str = "allowlist",
    verbose_mode: bool = True,
    approval_mode: str = "auto",
) -> dict:
    enabled_plugins: list[str] = ["telemetry-push"]
    if group_policy != "open":
        enabled_plugins.append("slack-channel-allowlist")
    if dm_policy != "open":
        enabled_plugins.append("slack-deny-dms")
    cfg = _hermes_config_core(
        model,
        litellm_base_url,
        enabled_plugins,
        display_platforms={
            "slack": {
                "tool_progress": "off",
                "interim_assistant_messages": verbose_mode,
                "busy_ack_detail": False,
            },
        },
        approval_mode=approval_mode,
    )
    cfg["slack"] = {
        "reply_in_thread": True,
        "broadcast_reply": False,
        "require_mention": True,
        "strict_mention": True,
        "unauthorized_dm_behavior": "ignore",
    }
    return cfg


def build_hermes_config_telegram(
    model: str,
    litellm_base_url: str,
    dm_policy: str = "off",
    group_policy: str = "allowlist",
    approval_mode: str = "auto",
) -> dict:
    enabled_plugins: list[str] = ["telemetry-push"]
    if group_policy != "open":
        enabled_plugins.append("telegram-channel-allowlist")
    if dm_policy != "open":
        enabled_plugins.append("telegram-deny-dms")
    cfg = _hermes_config_core(
        model,
        litellm_base_url,
        enabled_plugins,
        display_platforms={
            "telegram": {
                "tool_progress": "off",
            },
        },
        approval_mode=approval_mode,
    )
    cfg["telegram"] = {
        "require_mention": True,
        "exclusive_bot_mentions": True,
    }
    return cfg


def build_hermes_config_discord(
    model: str,
    litellm_base_url: str,
    require_mention: bool = True,
    group_policy: str = "allowlist",
    approval_mode: str = "auto",
) -> dict:
    enabled_plugins = ["telemetry-push", "discord-deny-dms"]
    if group_policy != "open":
        enabled_plugins.append("discord-guild-allowlist")
    cfg = _hermes_config_core(
        model,
        litellm_base_url,
        enabled_plugins,
        display_platforms={"discord": {"tool_progress": "off"}},
        approval_mode=approval_mode,
    )
    cfg["discord"] = {
        "require_mention": require_mention,
        "thread_require_mention": True,
        "auto_thread": True,
        "reactions": True,
        "allow_mentions": {"everyone": False, "roles": False},
    }
    return cfg


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
        "hermes-config.yaml": yaml.dump(hermes_config, default_flow_style=False, sort_keys=False),
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
    elif platform == "telegram":
        data["telegram-deny-dms-plugin.yaml"] = TELEGRAM_DENY_DMS_PLUGIN_YAML
        data["telegram-deny-dms-init.py"] = TELEGRAM_DENY_DMS_PLUGIN_INIT
        data["telegram-channel-allowlist-plugin.yaml"] = TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_YAML
        data["telegram-channel-allowlist-init.py"] = TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_INIT
    elif platform == "discord":
        data["discord-deny-dms-plugin.yaml"] = DISCORD_DENY_DMS_PLUGIN_YAML
        data["discord-deny-dms-init.py"] = DISCORD_DENY_DMS_PLUGIN_INIT
        data["discord-guild-allowlist-plugin.yaml"] = DISCORD_GUILD_ALLOWLIST_PLUGIN_YAML
        data["discord-guild-allowlist-init.py"] = DISCORD_GUILD_ALLOWLIST_PLUGIN_INIT
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
            "SLACK_HOME_CHANNEL": channel_ids[0] if channel_ids else _NO_SLACK_HOME_CHANNEL,
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
    dm_policy: str = "off",
    allowed_user_ids: list[str] | None = None,
    allowed_chat_ids: list[str] | None = None,
) -> client.V1Secret:
    allowed_dm_users = allowed_user_ids if dm_policy == "allowlist" else []
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
            "TELEGRAM_HOME_CHANNEL": allowed_chat_ids[0] if allowed_chat_ids else _NO_TELEGRAM_HOME_CHANNEL,
            "TELEGRAM_HOME_CHANNEL_NAME": allowed_chat_ids[0] if allowed_chat_ids else _NO_TELEGRAM_HOME_CHANNEL_NAME,
            "TELEGRAM_CHANNEL_IDS": ",".join(allowed_chat_ids or []),
            "TELEGRAM_DM_ALLOWED_USERS": ",".join(allowed_dm_users or []),
            "AGENT_PLATFORM": "telegram",
        },
    )


def build_secret_hermes_discord(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    agent_name: str,
    discord_bot_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
    api_server_key: str,
    allowed_channel_ids: list[str],
    allowed_user_ids: list[str],
    allowed_role_ids: list[str],
    home_channel_id: str | None,
    guild_ids: list[str],
) -> client.V1Secret:
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id), namespace=namespace, labels=_labels(agent_id, org_id)
        ),
        string_data={
            "DISCORD_BOT_TOKEN": discord_bot_token,
            "DISCORD_ALLOWED_CHANNELS": ",".join(allowed_channel_ids),
            "DISCORD_ALLOWED_USERS": ",".join(allowed_user_ids),
            "DISCORD_ALLOWED_ROLES": ",".join(allowed_role_ids),
            "DISCORD_GUILD_IDS": ",".join(guild_ids),
            "DISCORD_ALLOW_ALL_USERS": str(
                bool(guild_ids and not allowed_channel_ids and not allowed_user_ids and not allowed_role_ids)
            ).lower(),
            "DISCORD_HOME_CHANNEL": home_channel_id or _NO_DISCORD_HOME_CHANNEL,
            "DISCORD_HOME_CHANNEL_NAME": home_channel_id or "No Discord Home Channel",
            "DISCORD_ALLOW_BOTS": "none",
            "OPENAI_API_KEY": litellm_api_key,
            "OPENAI_BASE_URL": litellm_base_url,
            "OPENROUTER_BASE_URL": litellm_base_url,
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "0.0.0.0",
            "API_SERVER_PORT": "8642",
            "API_SERVER_KEY": api_server_key,
            "API_SERVER_MODEL_NAME": agent_name,
            "AGENT_PLATFORM": "discord",
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
