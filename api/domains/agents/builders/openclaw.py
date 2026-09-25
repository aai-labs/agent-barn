import json
from pathlib import Path
from uuid import UUID

from kubernetes import client

from api.domains.communications.models import ConversationLocation

from .common import _labels, _resource_name, _setting_ids

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
_OBSERVER = _SCRIPTS / "plugins" / "agentbarn-observer"

# OpenClaw's gateway binds this port and its own `openclaw health` CLI resolves
# the same value with no way to override it, so the runtime must not be moved
# off it. The in-pod communications adapter is pointed here to match.
OPENCLAW_GATEWAY_PORT = 18789

INIT_OPENCLAW_JS: str = (_SCRIPTS / "init-openclaw.js").read_text()
HEALTHZ_SERVER_JS: str = (_SCRIPTS / "healthz-server.js").read_text()
START_SH: str = (_SCRIPTS / "start.sh").read_text()
LEGACY_WORKSPACE_MIGRATION_SH: str = (_SCRIPTS / "legacy-workspace-migration.sh").read_text()
TELEMETRY_PUSH_INDEX_JS: str = (_TELEMETRY_PUSH / "index.js").read_text()
TELEMETRY_PUSH_PACKAGE_JSON: str = (_TELEMETRY_PUSH / "package.json").read_text()
TELEMETRY_PUSH_PLUGIN_JSON: str = (_TELEMETRY_PUSH / "openclaw.plugin.json").read_text()
OBSERVER_INDEX_JS: str = (_OBSERVER / "index.js").read_text()
OBSERVER_PACKAGE_JSON: str = (_OBSERVER / "package.json").read_text()
OBSERVER_PLUGIN_JSON: str = (_OBSERVER / "openclaw.plugin.json").read_text()
COMMUNICATIONS_RUNTIME_ADAPTER_PY: str = (_COMMON_SCRIPTS / "communications-runtime-adapter.py").read_text()
AGENT_TRIGGER_SERVER_PY: str = (_COMMON_SCRIPTS / "agent-trigger-server.py").read_text()

_MESSAGE_SCRIPTS = _COMMON_SCRIPTS / "messaging"
AGENTBARN_MESSAGE_PY: str = (_MESSAGE_SCRIPTS / "agentbarn_message.py").read_text()
OPENCLAW_MESSAGING_JS: str = (_MESSAGE_SCRIPTS / "openclaw-messaging.js").read_text()


# The agent workspace on the persistent volume; OpenClaw attaches local files from here.
OPENCLAW_WORKSPACE_DIR = "/home/node/.openclaw/workspace"


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
                "heartbeat": {"every": "0m", "target": "none"},
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
        "memory": {"search": {"provider": "none"}},
        # OpenClaw's default ("main") shares one session across every sender's DMs, so a
        # multi-user Agent would carry one person's private conversation into the next.
        "session": {"dmScope": "per-channel-peer"},
        "plugins": {
            "allow": ["memory-core", "active-memory", "telemetry-push", "agentbarn-messaging"],
            "load": {
                "paths": [
                    "/home/node/.openclaw/local-plugins/telemetry-push",
                    "/home/node/.openclaw/local-plugins/agentbarn-messaging",
                ]
            },
            "slots": {"memory": "memory-core"},
            "entries": {
                "memory-core": {"enabled": True},
                "agentbarn-messaging": {"enabled": True},
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


_OBSERVER_PLUGIN_PATH = "/home/node/.openclaw/local-plugins/agentbarn-observer"
_NO_HOME_CHANNEL_TARGET = "channel:__agentbarn_no_home_channel__"


def build_openclaw_gateway_config(
    model: str,
    litellm_base_url: str,
    native_channels: dict[str, dict] | None = None,
) -> dict:
    """``native_channels`` maps a Platform key to its OpenClaw ``channels.<key>`` block."""
    channels = native_channels or {}
    config = _openclaw_config_core(model, litellm_base_url, binding_channel=None, channels=channels)
    if channels:
        plugins = config["plugins"]
        plugins["allow"] += [*channels, "agentbarn-observer"]
        # start.sh installs non-bundled channel plugins from npm; OpenClaw only grants plugin
        # state to official installs, so they must not be loaded by path.
        plugins["load"]["paths"].append(_OBSERVER_PLUGIN_PATH)
        for key in channels:
            plugins["entries"][key] = {"enabled": True}
        plugins["entries"]["agentbarn-observer"] = {"enabled": True, "hooks": {"allowConversationAccess": True}}
    return config


def native_slack_channel(settings: dict, home_channel: ConversationLocation | None = None) -> dict:
    """Map a Slack Connection's policy onto OpenClaw's native Slack channel.

    Tokens stay in the Secret (``SLACK_BOT_TOKEN``/``SLACK_APP_TOKEN``), not the
    config file persisted on the PVC.
    """
    dm_policy = settings.get("dm_policy", "off")
    channel = {
        "enabled": True,
        "mode": "socket",
        "requireMention": True,
        "replyToMode": "all",
        # Replies stream through Slack's native API as markdown_text, so Slack renders
        # tables; OpenClaw's plain send would convert them to fenced code.
        "streaming": {"mode": "partial"},
        "groupPolicy": settings.get("group_policy", "allowlist"),
        # start_only accepts unmentioned replies in threads the Agent already joined.
        "implicitMentions": {"threadParticipation": settings.get("thread_mention_policy") == "start_only"},
        "dmPolicy": {"off": "disabled"}.get(dm_policy, dm_policy),
        # OpenClaw drops inbound files over 20 MB by default, which rules out meeting
        # recordings (an hour of MP3 is ~60-90 MB). The pod's 1 GiB limit covers 100 MB.
        "mediaMaxMb": 100,
    }
    if channel["groupPolicy"] == "allowlist":
        channel["channels"] = {channel_id: {"enabled": True} for channel_id in settings.get("channel_ids") or []}
    if dm_policy == "open":
        channel["allowFrom"] = ["*"]
    elif dm_policy == "allowlist":
        channel["allowFrom"] = list(settings.get("dm_user_ids") or [])
    if home_channel is not None:
        # ponytail: a home thread is dropped; cron results post top-level in the home channel.
        channel["defaultTo"] = f"channel:{home_channel.id}"
    else:
        # OpenClaw shows an in-chat setup prompt when defaultTo is absent. Keep
        # intentionally-unconfigured Connections quiet without selecting a real
        # channel for originless proactive messages.
        channel["defaultTo"] = _NO_HOME_CHANNEL_TARGET
    return channel


def native_discord_channel(settings: dict) -> dict:
    """Map a Discord Connection's global gates onto OpenClaw's native Discord channel.

    Agent Barn's channel, user, and role allowlists are not guild-scoped, so they
    apply to every guild through OpenClaw's ``"*"`` guild entry.
    """
    allow_all = bool(settings.get("allow_all_users"))
    users = _setting_ids(settings, "allowed_user_ids")
    roles = _setting_ids(settings, "allowed_role_ids")
    channel_ids = _setting_ids(settings, "allowed_channel_ids")
    channel: dict = {"enabled": True, "groupPolicy": "allowlist"}
    guild: dict = {"requireMention": settings.get("require_mention", True)}
    if not allow_all:
        if users:
            guild["users"] = users
        if roles:
            guild["roles"] = roles
    # Reply in a thread per message, as Hermes does. Threads inherit their parent
    # channel's entry, and "*" keeps an empty channel allowlist unrestricted.
    # ponytail: OpenClaw skips requireMention inside threads the bot created, and
    # has no switch to keep it; Hermes still requires the mention there.
    guild["channels"] = {channel_id: {"enabled": True, "autoThread": True} for channel_id in channel_ids or ["*"]}
    if allow_all or users or roles or channel_ids:
        channel["guilds"] = {"*": guild}
    else:
        channel["groupPolicy"] = "disabled"
    # Roles cannot be resolved without a guild, so DMs admit listed users only.
    if allow_all:
        channel.update(dmPolicy="open", allowFrom=["*"])
    elif users:
        channel.update(dmPolicy="allowlist", allowFrom=users)
    else:
        channel["dmPolicy"] = "disabled"
    if home_channel_id := settings.get("home_channel_id"):
        channel["defaultTo"] = f"channel:{home_channel_id}"
    else:
        channel["defaultTo"] = _NO_HOME_CHANNEL_TARGET
    return channel


def native_telegram_channel(settings: dict) -> dict:
    """Map a Telegram Connection onto OpenClaw's bundled Telegram channel.

    ``groups`` is the group allowlist and ``groupPolicy: "open"`` admits any member
    of those groups. Groups always require a mention; DMs never do.
    """
    channel: dict = {"enabled": True, "dmPolicy": "disabled", "groupPolicy": "disabled"}
    user_ids = _setting_ids(settings, "allowed_user_ids")
    dm_policy = settings.get("dm_policy", "off")
    if dm_policy == "open":
        channel.update(dmPolicy="open", allowFrom=["*"])
    elif dm_policy == "allowlist" and user_ids:
        # An empty allowlist drops every DM anyway and OpenClaw warns about it.
        channel.update(dmPolicy="allowlist", allowFrom=user_ids)
    group_ids = (
        ["*"] if settings.get("group_policy", "allowlist") == "open" else _setting_ids(settings, "allowed_chat_ids")
    )
    if group_ids:
        channel["groupPolicy"] = "open"
        channel["groups"] = {group_id: {"requireMention": True} for group_id in group_ids}
    if home_channel_id := settings.get("home_channel_id"):
        channel["defaultTo"] = str(home_channel_id)
    else:
        channel["defaultTo"] = _NO_HOME_CHANNEL_TARGET
    return channel


def runtime_teams_channel(settings: dict) -> dict:
    """Configure OpenClaw's runtime-owned Microsoft Teams webhook adapter.

    Credentials remain Kubernetes Secret values and are read from OpenClaw's
    documented ``MSTEAMS_*`` environment variables rather than being written to
    its persistent config.
    Agent Barn's public relay owns Connection policy enforcement.
    """
    channel = {
        "enabled": True,
        "webhook": {"port": 3978, "path": "/api/messages"},
        "dmPolicy": "open",
        "allowFrom": ["*"],
        "groupPolicy": "open",
        "groupAllowFrom": ["*"],
    }
    if home_channel_id := settings.get("home_channel_id"):
        channel["defaultTo"] = f"conversation:{home_channel_id}"
    else:
        channel["defaultTo"] = "conversation:__agentbarn_no_home_channel__"
    return channel


def native_channel_env(credentials_by_platform: dict[str, dict]) -> dict[str, str]:
    """Secret entries for native channel tokens and the observer."""
    env = {
        "AGENTBARN_NATIVE_CHANNELS": ",".join(credentials_by_platform),
        # The native gateway delivers scheduled results to their origin or defaultTo.
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
    }
    if slack := credentials_by_platform.get("slack"):
        env["SLACK_BOT_TOKEN"] = slack["bot_token"]
        env["SLACK_APP_TOKEN"] = slack["app_token"]
    if discord := credentials_by_platform.get("discord"):
        env["DISCORD_BOT_TOKEN"] = discord["bot_token"]
    if telegram := credentials_by_platform.get("telegram"):
        env["TELEGRAM_BOT_TOKEN"] = telegram["bot_token"]
    if teams := credentials_by_platform.get("msteams"):
        env["MSTEAMS_APP_ID"] = teams["app_id"]
        env["MSTEAMS_APP_PASSWORD"] = teams["app_password"]
        env["MSTEAMS_TENANT_ID"] = teams["tenant_id"]
    return env


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
        data["legacy-workspace-migration.sh"] = LEGACY_WORKSPACE_MIGRATION_SH
        data["telemetry-push-index.js"] = TELEMETRY_PUSH_INDEX_JS
        data["telemetry-push-package.json"] = TELEMETRY_PUSH_PACKAGE_JSON
        data["telemetry-push-plugin.json"] = TELEMETRY_PUSH_PLUGIN_JSON
        data["agentbarn-observer-index.js"] = OBSERVER_INDEX_JS
        data["agentbarn-observer-package.json"] = OBSERVER_PACKAGE_JSON
        data["agentbarn-observer-plugin.json"] = OBSERVER_PLUGIN_JSON
        data["communications-runtime-adapter.py"] = COMMUNICATIONS_RUNTIME_ADAPTER_PY
        data["agent-trigger-server.py"] = AGENT_TRIGGER_SERVER_PY
        data["agentbarn_message.py"] = AGENTBARN_MESSAGE_PY
        data["openclaw-messaging.js"] = OPENCLAW_MESSAGING_JS
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
            "RUNTIME_KIND": "openclaw",
            "AGENT_TRIGGER_RECEIPT_PATH": "/home/node/.openclaw/agent-trigger-receipts.sqlite3",
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
