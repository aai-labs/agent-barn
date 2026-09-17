from pathlib import Path
from uuid import UUID

import yaml
from kubernetes import client

from api.domains.communications.models import ConversationLocation

from .common import _labels, _resource_name

# Matches OpenClaw, so limits.memory (100Gi quota) never binds before
# requests.memory (20Gi). Note the asymmetry in what the limit *does*: OpenClaw
# is Node, and V8 derives its heap ceiling from the cgroup limit (measured
# 259/524/1048 MiB at 512m/1g/2g), so a lower limit makes it collect sooner.
# CPython collects promptly too, but its policy is allocation-count based and
# never reads the cgroup, so here the limit is a hard cap on the real working
# set rather than a GC trigger. No Hermes pod is known to exceed 1Gi -- the
# runtime label added alongside this is what will confirm it -- so watch for
# OOMKilled on Hermes after rollout.
AGENT_RESOURCES = client.V1ResourceRequirements(
    requests={"memory": "320Mi", "cpu": "50m"},
    limits={"memory": "1Gi", "cpu": "500m"},
)

_SCRIPTS = Path(__file__).parent.parent / "scripts" / "hermes"
_COMMON_SCRIPTS = _SCRIPTS.parent
_TELEMETRY_PUSH = _SCRIPTS / "plugins" / "telemetry-push"
_OBSERVER = _SCRIPTS / "plugins" / "agentbarn-observer"

HERMES_BOOTLOADER_FOOTER: str = (_SCRIPTS / "bootloader-footer.md").read_text()
HERMES_CONFIG_MERGE_PY: str = (_SCRIPTS / "config-merge.py").read_text()
HERMES_HEALTHZ_PY: str = (_SCRIPTS / "healthz-server.py").read_text()
HERMES_START_SH: str = (_SCRIPTS / "start.sh").read_text()
TELEMETRY_PUSH_PLUGIN_YAML: str = (_TELEMETRY_PUSH / "plugin.yaml").read_text()
TELEMETRY_PUSH_PLUGIN_INIT: str = (_TELEMETRY_PUSH / "__init__.py").read_text()
OBSERVER_PLUGIN_YAML: str = (_OBSERVER / "plugin.yaml").read_text()
OBSERVER_PLUGIN_INIT: str = (_OBSERVER / "__init__.py").read_text()
COMMUNICATIONS_RUNTIME_ADAPTER_PY: str = (_COMMON_SCRIPTS / "communications-runtime-adapter.py").read_text()


_HERMES_APPROVAL_MODE = {"manual": "manual", "auto": "smart", "off": "off"}
_HERMES_APPROVAL_TIMEOUT_SECONDS = 300
_HERMES_HEADLESS_APPROVAL_MODE = "deny"
# Hermes shows a first-message onboarding notice whenever this variable is
# absent. This deliberately cannot be a Slack channel ID: it suppresses that
# notice without accidentally making an arbitrary real channel the destination
# for proactive messages.
_SLACK_NO_HOME_CHANNEL = "__agentbarn_no_home_channel__"
_DISCORD_NO_HOME_CHANNEL = "__agentbarn_no_home_channel__"
# Every auxiliary.<task> block v2026.8.19 reads, minus the moa_* slots (MoA only).
_HERMES_AUXILIARY_TASKS = (
    "vision",
    "web_extract",
    "compression",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "memory_query_rewrite",
    "tts_audio_tags",
    "triage_specifier",
    "kanban_decomposer",
    "profile_describer",
    "goal_judge",
    "curator",
    "monitor",
    "background_review",
)

_MESSAGE_SCRIPTS = _COMMON_SCRIPTS / "messaging"
HERMES_BOOT_RUN_PY: str = (_SCRIPTS / "boot-run.py").read_text()


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
        # Agent Barn materializes pinned Skills in the persistent workspace,
        # while Hermes otherwise scans only $HERMES_HOME/skills.
        "skills": {
            "external_dirs": ["/workspace/skills"],
        },
        "approvals": {
            "mode": _HERMES_APPROVAL_MODE.get(approval_mode, "smart"),
            "timeout": _HERMES_APPROVAL_TIMEOUT_SECONDS,
            "cron_mode": _HERMES_HEADLESS_APPROVAL_MODE,
            "single_query_mode": _HERMES_HEADLESS_APPROVAL_MODE,
        },
        # Left on "auto", auxiliary tasks resolve via provider=openrouter, find no
        # OPENROUTER_API_KEY, and fall back to a keyless client the LiteLLM proxy
        # rejects: smart approval escalated every flagged command, and title
        # generation and vision failed. "custom" reuses OPENAI_API_KEY from the
        # runtime secret against the same proxy. The main model stays on
        # "openrouter" because "custom" there drops that key.
        "auxiliary": {
            task: {"provider": "custom", "base_url": litellm_base_url, "model": model_name}
            for task in _HERMES_AUXILIARY_TASKS
        },
    }


def build_hermes_gateway_config(
    model: str,
    litellm_base_url: str,
    approval_mode: str = "auto",
    native_slack: bool = False,
    native_discord: bool = False,
    discord_require_mention: bool = True,
    verbose_mode: bool = False,
) -> dict:
    plugins = ["telemetry-push", "agentbarn-messaging"]
    if native_slack or native_discord:
        plugins.append("agentbarn-observer")
    config = _hermes_config_core(model, litellm_base_url, enabled_plugins=plugins, approval_mode=approval_mode)
    if native_slack:
        config["slack"] = {
            "reply_in_thread": True,
            "reply_broadcast": False,
            # Unknown DM senders would otherwise receive a pairing code.
            "unauthorized_dm_behavior": "ignore",
        }
        # Slack's markdown block renders standard markdown, tables included, where
        # mrkdwn would fence them as code. Hermes resends plain mrkdwn if rejected.
        config["platforms"] = {"slack": {"extra": {"markdown_blocks": True}}}
        # The Agent's Verbose mode. Progress accumulates in one edited message
        # rather than a permanent Slack line per tool call.
        config["display"]["platforms"]["slack"] = {
            "tool_progress": "all" if verbose_mode else "off",
            "tool_progress_grouping": "accumulate",
            "interim_assistant_messages": verbose_mode,
        }
    if native_discord:
        config["discord"] = {
            # Agent Barn's Discord contract requires the same mention policy in
            # parent channels and threads. Hermes otherwise keeps responding in
            # a thread after its first turn without another mention.
            "require_mention": discord_require_mention,
            "thread_require_mention": discord_require_mention,
        }
        config["display"]["platforms"]["discord"] = {
            "tool_progress": "all" if verbose_mode else "off",
            "tool_progress_grouping": "accumulate",
            "interim_assistant_messages": verbose_mode,
        }
    return config


def native_slack_env(
    settings: dict,
    credentials: dict,
    home_channel: ConversationLocation | None = None,
) -> dict[str, str]:
    """Map a Slack Connection onto the native Hermes Slack adapter's environment.

    ``home_channel`` is the Connection's resolved default delivery target, which
    native cron jobs without an origin deliver to.

    ponytail: Hermes has one user allowlist for channels and DMs alike, so a DM
    allowlist also restricts channel senders; model it separately if that matters
    beyond the spike.
    """
    env = {
        "SLACK_BOT_TOKEN": credentials["bot_token"],
        "SLACK_APP_TOKEN": credentials["app_token"],
        "SLACK_REQUIRE_MENTION": "true",
        "SLACK_THREAD_REQUIRE_MENTION": "true" if settings.get("thread_mention_policy") != "start_only" else "false",
        "SLACK_DISABLE_DMS": "true" if settings.get("dm_policy", "off") == "off" else "false",
        # Hermes delivers scheduled results itself, to their origin or the home
        # channel, instead of bridging them through the Communications gateway.
        # ponytail: disables the bridge for every origin, so Web Chat cron jobs go
        # undelivered on native agents; route per origin once transport is per Connection.
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
    }
    if settings.get("group_policy", "allowlist") == "allowlist":
        env["SLACK_ALLOWED_CHANNELS"] = ",".join(settings.get("channel_ids") or [])
    if settings.get("dm_policy") == "allowlist":
        env["SLACK_ALLOWED_USERS"] = ",".join(settings.get("dm_user_ids") or [])
    else:
        env["SLACK_ALLOW_ALL_USERS"] = "true"
    if home_channel is not None:
        env["SLACK_HOME_CHANNEL"] = home_channel.id
        env["SLACK_HOME_CHANNEL_NAME"] = home_channel.display_name or ""
        if home_channel.thread_id:
            env["SLACK_HOME_CHANNEL_THREAD_ID"] = home_channel.thread_id
    else:
        # Hermes uses only the presence of this variable to decide whether to
        # show its home-channel onboarding message. A sentinel keeps an
        # intentionally-unconfigured Connection quiet; an originless native
        # cron delivery still fails safely rather than landing in a real channel.
        env["SLACK_HOME_CHANNEL"] = _SLACK_NO_HOME_CHANNEL
    return env


def native_discord_env(settings: dict, credentials: dict) -> dict[str, str]:
    """Map the Discord Connection's native Hermes authorization gates."""
    env = {
        "DISCORD_BOT_TOKEN": credentials["bot_token"],
        "DISCORD_ALLOW_ALL_USERS": "true" if settings.get("allow_all_users") else "false",
        # Native Hermes delivers scheduled results to their origin or home.
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
    }
    for settings_key, env_key in (
        ("allowed_channel_ids", "DISCORD_ALLOWED_CHANNELS"),
        ("allowed_user_ids", "DISCORD_ALLOWED_USERS"),
        ("allowed_role_ids", "DISCORD_ALLOWED_ROLES"),
    ):
        values = [str(value) for value in settings.get(settings_key, []) if str(value)]
        if values:
            env[env_key] = ",".join(values)
    if home_channel_id := settings.get("home_channel_id"):
        env["DISCORD_HOME_CHANNEL"] = str(home_channel_id)
    else:
        env["DISCORD_HOME_CHANNEL"] = _DISCORD_NO_HOME_CHANNEL
    return env


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
        "agentbarn-observer-plugin.yaml": OBSERVER_PLUGIN_YAML,
        "agentbarn-observer-init.py": OBSERVER_PLUGIN_INIT,
        "healthz-server.py": HERMES_HEALTHZ_PY,
        "config-merge.py": HERMES_CONFIG_MERGE_PY,
        "start.sh": HERMES_START_SH,
        "communications-runtime-adapter.py": COMMUNICATIONS_RUNTIME_ADAPTER_PY,
        "agentbarn_message.py": (_MESSAGE_SCRIPTS / "agentbarn_message.py").read_text(),
        "hermes-messaging.py": (_MESSAGE_SCRIPTS / "hermes-messaging.py").read_text(),
        "boot-run.py": HERMES_BOOT_RUN_PY,
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
    verbose_mode: bool = False,
    approval_mode: str = "auto",
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
            # Only in-pod callers (adapter, boot-run, healthz) reach the API server,
            # and the Service does not expose it; loopback keeps the unsandboxed
            # terminal off the pod network.
            "API_SERVER_HOST": "127.0.0.1",
            "API_SERVER_PORT": "8642",
            "API_SERVER_KEY": runtime_api_key,
            "API_SERVER_MODEL_NAME": agent_name,
            "RUNTIME_API_KEY": runtime_api_key,
            "RUNTIME_API_URL": "http://127.0.0.1:8642",
            "RUNTIME_MODEL": agent_name,
            "RUNTIME_KIND": "hermes",
            "VERBOSE_MODE": "true" if verbose_mode else "false",
            "APPROVAL_MODE": approval_mode,
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
    labels = _labels(agent_id, org_id, runtime="hermes")

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            # See the OpenClaw builder: RWO PVC + surge = doubled memory and a
            # volume deadlock on every config change.
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
                            command=[
                                "sh",
                                "-c",
                                "mkdir -p /opt/data/workspace && chown -R hermes:hermes /opt/data",
                            ],
                            security_context=client.V1SecurityContext(run_as_user=0),
                            volume_mounts=[
                                client.V1VolumeMount(name="data", mount_path="/opt/data"),
                            ],
                        )
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
