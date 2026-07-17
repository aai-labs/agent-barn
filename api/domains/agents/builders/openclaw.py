import json
from pathlib import Path
from uuid import UUID

from kubernetes import client

from .common import _labels, _resource_name

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "openclaw"
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"

INIT_OPENCLAW_JS: str = (_SCRIPTS / "init-openclaw.js").read_text()
HEALTHZ_SERVER_JS: str = (_SCRIPTS / "healthz-server.js").read_text()
START_SH: str = (_SCRIPTS / "start.sh").read_text()
TELEMETRY_PUSH_INDEX_JS: str = (_TELEMETRY_PUSH / "index.js").read_text()
TELEMETRY_PUSH_PACKAGE_JSON: str = (_TELEMETRY_PUSH / "package.json").read_text()
TELEMETRY_PUSH_PLUGIN_JSON: str = (_TELEMETRY_PUSH / "openclaw.plugin.json").read_text()


def build_openclaw_config_overlay(
    model: str,
    litellm_base_url: str,
    slack_channel_ids: list[str] | None = None,
    slack_dm_user_ids: list[str] | None = None,
    slack_group_policy: str = "open",
    slack_dm_policy: str = "open",
    approval_mode: str = "auto",
    firecrawl_base_url: str = "",
    firecrawl_api_key: str = "",
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
        channel_id: {"enabled": True, "requireMention": True}
        for channel_id in channel_ids
    }

    overlay = {
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
        "gateway": {"auth": {"mode": "none"}},
    }
    if firecrawl_base_url and firecrawl_api_key:
        overlay["plugins"]["allow"].append("firecrawl")
        overlay["plugins"]["entries"]["firecrawl"] = {
            "enabled": True,
            "config": {
                "webSearch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                },
                "webFetch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                    "onlyMainContent": True,
                    "maxAgeMs": 172800000,
                    "timeoutSeconds": 60,
                },
            },
        }
        overlay["tools"]["web"] = {
            "fetch": {"provider": "firecrawl"},
            "search": {"enabled": True, "provider": "firecrawl"},
        }
    return overlay


def build_openclaw_config_overlay_teams(
    model: str,
    litellm_base_url: str,
    approval_mode: str = "auto",
    firecrawl_base_url: str = "",
    firecrawl_api_key: str = "",
) -> dict:
    provider, _, model_name = model.partition("/")

    overlay = {
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
        "gateway": {"auth": {"mode": "none"}},
    }
    if firecrawl_base_url and firecrawl_api_key:
        overlay["plugins"]["allow"].append("firecrawl")
        overlay["plugins"]["entries"]["firecrawl"] = {
            "enabled": True,
            "config": {
                "webSearch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                },
                "webFetch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                    "onlyMainContent": True,
                    "maxAgeMs": 172800000,
                    "timeoutSeconds": 60,
                },
            },
        }
        overlay["tools"]["web"] = {
            "fetch": {"provider": "firecrawl"},
            "search": {"enabled": True, "provider": "firecrawl"},
        }
    return overlay


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


def build_secret_slack(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    slack_bot_token: str,
    slack_app_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
    firecrawl_api_key: str = "",
) -> client.V1Secret:
    string_data = {
        "SLACK_BOT_TOKEN": slack_bot_token,
        "SLACK_APP_TOKEN": slack_app_token,
        "LITELLM_API_KEY": litellm_api_key,
        "LITELLM_BASE_URL": litellm_base_url,
    }
    if firecrawl_api_key:
        string_data["FIRECRAWL_API_KEY"] = firecrawl_api_key
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data=string_data,
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
    firecrawl_api_key: str = "",
) -> client.V1Secret:
    string_data = {
        "MSTEAMS_APP_ID": msteams_app_id,
        "MSTEAMS_APP_PASSWORD": msteams_app_password,
        "MSTEAMS_TENANT_ID": msteams_tenant_id,
        "LITELLM_API_KEY": litellm_api_key,
        "LITELLM_BASE_URL": litellm_base_url,
    }
    if firecrawl_api_key:
        string_data["FIRECRAWL_API_KEY"] = firecrawl_api_key
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data=string_data,
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
