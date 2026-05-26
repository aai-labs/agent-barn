import datetime
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.domains.agents.builders import (
    build_config_map,
    build_deployment,
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_teams,
    build_pvc,
    build_secret_slack,
    build_secret_teams,
    build_service,
)
from api.domains.agents.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
    DEFAULT_TOOLS_MD,
    DEFAULT_USER_MD,
)
from api.domains.agents.models import (
    Agent,
    AgentCreate,
    AgentFilter,
    AgentHealthRead,
    AgentPlatform,
    AgentRead,
    AgentSlackConfig,
    AgentSlackConfigRead,
    AgentStatus,
    AgentTeamsConfig,
    AgentTeamsConfigRead,
    AgentTemplate,
    AgentTemplateRead,
    AgentUpdate,
    PairRequest,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.conversations.service import ConversationSyncService
from api.domains.tool_calls.sync_service import ToolCallSyncService
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.shared.models import PaginatedItems, Pagination
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)

_MD_FIELDS = frozenset(
    {
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    }
)

_SLACK_CONFIG_FIELDS = frozenset(
    {
        "slack_bot_token",
        "slack_app_token",
        "slack_channel_ids",
        "slack_dm_user_ids",
        "slack_group_policy",
        "slack_dm_policy",
    }
)

_TEAMS_CONFIG_FIELDS = frozenset(
    {
        "teams_app_id",
        "teams_app_password",
        "teams_tenant_id",
    }
)


@inject
@singleton
@dataclass
class AgentService:
    repository: AgentRepository
    k8s: KubernetesClient
    litellm: LiteLLMClient
    config: Config
    conversation_sync_service: ConversationSyncService
    sync_service: ToolCallSyncService

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _get_active_or_404(self, agent_id: UUID, org_id: UUID) -> Agent:
        agent = self.repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )
        return agent

    def _build_agent_read(
        self,
        agent: Agent,
        slack_config: AgentSlackConfig | None = None,
        teams_config: AgentTeamsConfig | None = None,
    ) -> AgentRead:
        slack_config_read = (
            AgentSlackConfigRead.model_validate(slack_config) if slack_config else None
        )
        teams_config_read = (
            AgentTeamsConfigRead.model_validate(teams_config) if teams_config else None
        )
        webhook_url = (
            f"{self.config.api_external_url}/api/v1/webhooks/teams/{agent.id}/messages"
            if agent.platform == AgentPlatform.TEAMS and self.config.api_external_url
            else None
        )
        return AgentRead(
            id=agent.id,
            name=agent.name,
            status=agent.status,
            platform=agent.platform,
            organization_id=agent.organization_id,
            template_id=agent.template_id,
            template_version=agent.template_version,
            model=agent.model,
            slack_config=slack_config_read,
            teams_config=teams_config_read,
            webhook_url=webhook_url,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _get_agent_read(self, agent: Agent) -> AgentRead:
        slack_config = None
        teams_config = None
        if agent.platform == AgentPlatform.SLACK:
            slack_config = self.repository.get_slack_config(agent.id)
        elif agent.platform == AgentPlatform.TEAMS:
            teams_config = self.repository.get_teams_config(agent.id)
        return self._build_agent_read(agent, slack_config, teams_config)

    def create_agent(self, data: AgentCreate, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)

        agent = Agent(
            organization_id=org_id,
            name=data.name,
            model=data.model or "",
            platform=data.platform,
            template_id=None,  # ty: ignore[invalid-argument-type]
            template_version=0,
        )

        if self.config.litellm_base_url and self.config.litellm_secret_name:
            try:
                litellm_key = self.litellm.generate_key(str(agent.id))
                agent.litellm_key_encrypted = encrypt_token(
                    litellm_key, self.config.agent_token_encryption_key
                )
            except LiteLLMError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="LiteLLM key generation failed; cannot create agent.",
                ) from exc

        template = AgentTemplate(
            organization_id=org_id,
            version=1,
            soul_md=data.soul_md,
            identity_md=data.identity_md,
            user_md=data.user_md or DEFAULT_USER_MD,
            tools_md=data.tools_md or DEFAULT_TOOLS_MD,
            agents_md=data.agents_md or DEFAULT_AGENTS_MD,
            boot_md=data.boot_md or DEFAULT_BOOT_MD,
            bootstrap_md=data.bootstrap_md or DEFAULT_BOOTSTRAP_MD,
            heartbeat_md=data.heartbeat_md or DEFAULT_HEARTBEAT_MD,
        )
        self.repository.save_template(template)

        agent.template_id = template.id
        agent.template_version = template.version
        self.repository.save(agent)

        template.agent_id = agent.id
        self.repository.save_template(template)

        slack_config = None
        teams_config = None

        if data.platform == AgentPlatform.SLACK:
            slack_config = AgentSlackConfig(
                agent_id=agent.id,
                bot_token_encrypted=encrypt_token(
                    data.slack_bot_token,
                    self.config.agent_token_encryption_key,  # type: ignore[arg-type]
                ),
                app_token_encrypted=encrypt_token(
                    data.slack_app_token,
                    self.config.agent_token_encryption_key,  # type: ignore[arg-type]
                ),
                channel_ids=data.slack_channel_ids,
                dm_user_ids=data.slack_dm_user_ids,
                group_policy=data.slack_group_policy,
                dm_policy=data.slack_dm_policy,
            )
            self.repository.save_slack_config(slack_config)
        elif data.platform == AgentPlatform.TEAMS:
            teams_config = AgentTeamsConfig(
                agent_id=agent.id,
                app_id_encrypted=encrypt_token(
                    data.teams_app_id,
                    self.config.agent_token_encryption_key,  # type: ignore[arg-type]
                ),
                app_password_encrypted=encrypt_token(
                    data.teams_app_password,
                    self.config.agent_token_encryption_key,  # type: ignore[arg-type]
                ),
                tenant_id=data.teams_tenant_id,  # type: ignore[arg-type]
            )
            self.repository.save_teams_config(teams_config)

        return self._build_agent_read(agent, slack_config, teams_config)

    def get_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        return self._get_agent_read(agent)

    def get_agent_template(
        self, agent_id: UUID, version: int, context: CurrentUserContext
    ) -> AgentTemplateRead:
        org_id = self._org_id(context)
        self._get_active_or_404(agent_id, org_id)
        template = self.repository.get_template_by_agent_and_version(
            agent_id, version, org_id
        )
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template version {version} not found for agent {agent_id}",
            )
        return AgentTemplateRead.model_validate(template)

    def list_agents(
        self,
        agent_filter: AgentFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[AgentRead]:
        org_id = self._org_id(context)
        agents, total = self.repository.find_all_active(
            org_id, agent_filter, pagination
        )

        agent_ids = [a.id for a in agents]
        slack_configs = self.repository.get_slack_configs_for_agents(agent_ids)
        teams_configs = self.repository.get_teams_configs_for_agents(agent_ids)

        items = [
            self._build_agent_read(
                agent,
                slack_configs.get(agent.id),
                teams_configs.get(agent.id),
            )
            for agent in agents
        ]

        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=items,
        )

    def update_agent(
        self, agent_id: UUID, data: AgentUpdate, context: CurrentUserContext
    ) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)

        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} must be stopped before updating",
            )

        updated = data.model_dump(exclude_unset=True)

        if agent.platform == AgentPlatform.TEAMS and (
            _SLACK_CONFIG_FIELDS & updated.keys()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot set Slack fields on a Teams agent",
            )
        if agent.platform == AgentPlatform.SLACK and (
            _TEAMS_CONFIG_FIELDS & updated.keys()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot set Teams fields on a Slack agent",
            )

        if _MD_FIELDS & updated.keys():
            old_template = self.repository.get_template(agent.template_id)
            new_template = AgentTemplate(
                organization_id=org_id,
                agent_id=agent.id,
                version=old_template.version + 1,
                soul_md=updated.get("soul_md", old_template.soul_md),
                identity_md=updated.get("identity_md", old_template.identity_md),
                user_md=updated.get("user_md", old_template.user_md),
                tools_md=updated.get("tools_md", old_template.tools_md),
                agents_md=updated.get("agents_md", old_template.agents_md),
                boot_md=updated.get("boot_md", old_template.boot_md),
                bootstrap_md=updated.get("bootstrap_md", old_template.bootstrap_md),
                heartbeat_md=updated.get("heartbeat_md", old_template.heartbeat_md),
            )
            self.repository.save_template(new_template)
            agent.template_id = new_template.id
            agent.template_version = new_template.version

        if "name" in updated:
            agent.name = updated["name"]

        if "model" in updated:
            agent.model = updated["model"]

        # Slack config updates
        if agent.platform == AgentPlatform.SLACK and (
            _SLACK_CONFIG_FIELDS & updated.keys()
        ):
            slack_config = self.repository.get_slack_config(agent.id)
            if slack_config:
                if "slack_bot_token" in updated:
                    slack_config.bot_token_encrypted = encrypt_token(
                        updated["slack_bot_token"],
                        self.config.agent_token_encryption_key,
                    )
                if "slack_app_token" in updated:
                    slack_config.app_token_encrypted = encrypt_token(
                        updated["slack_app_token"],
                        self.config.agent_token_encryption_key,
                    )
                if "slack_channel_ids" in updated:
                    slack_config.channel_ids = updated["slack_channel_ids"]
                if "slack_dm_user_ids" in updated:
                    slack_config.dm_user_ids = updated["slack_dm_user_ids"]
                if "slack_group_policy" in updated:
                    slack_config.group_policy = updated["slack_group_policy"]
                if "slack_dm_policy" in updated:
                    slack_config.dm_policy = updated["slack_dm_policy"]
                self.repository.save_slack_config(slack_config)

        # Teams config updates
        if agent.platform == AgentPlatform.TEAMS and (
            _TEAMS_CONFIG_FIELDS & updated.keys()
        ):
            teams_config = self.repository.get_teams_config(agent.id)
            if teams_config:
                if "teams_app_id" in updated:
                    teams_config.app_id_encrypted = encrypt_token(
                        updated["teams_app_id"], self.config.agent_token_encryption_key
                    )
                if "teams_app_password" in updated:
                    teams_config.app_password_encrypted = encrypt_token(
                        updated["teams_app_password"],
                        self.config.agent_token_encryption_key,
                    )
                if "teams_tenant_id" in updated:
                    teams_config.tenant_id = updated["teams_tenant_id"]
                self.repository.save_teams_config(teams_config)

        self.repository.save(agent)
        return self._get_agent_read(agent)

    def start_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)

        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is already running",
            )

        template = self.repository.get_template(agent.template_id)
        ns = self.config.k8s_namespace

        name = f"agent-{agent.id}"
        litellm_key = (
            decrypt_token(
                agent.litellm_key_encrypted, self.config.agent_token_encryption_key
            )
            if agent.litellm_key_encrypted
            else ""
        )
        effective_model = agent.model or self.config.agent_default_model

        if agent.platform == AgentPlatform.SLACK:
            slack_config = self.repository.get_slack_config(agent.id)
            if not slack_config:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Slack config missing for agent {agent_id}",
                )
            bot_token = decrypt_token(
                slack_config.bot_token_encrypted, self.config.agent_token_encryption_key
            )
            app_token = decrypt_token(
                slack_config.app_token_encrypted, self.config.agent_token_encryption_key
            )
            overlay = build_openclaw_config_overlay(
                effective_model,
                self.config.agent_litellm_base_url,
                slack_channel_ids=slack_config.channel_ids,
                slack_dm_user_ids=slack_config.dm_user_ids,
                slack_group_policy=str(slack_config.group_policy),
                slack_dm_policy=str(slack_config.dm_policy),
            )
            secret = build_secret_slack(
                agent_id=agent.id,
                org_id=org_id,
                namespace=ns,
                slack_bot_token=bot_token,
                slack_app_token=app_token,
                litellm_api_key=litellm_key,
                litellm_base_url=self.config.agent_litellm_base_url,
            )
            service = build_service(agent.id, org_id, ns)
        elif agent.platform == AgentPlatform.TEAMS:
            teams_config = self.repository.get_teams_config(agent.id)
            if not teams_config:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Teams config missing for agent {agent_id}",
                )
            app_id = decrypt_token(
                teams_config.app_id_encrypted, self.config.agent_token_encryption_key
            )
            app_password = decrypt_token(
                teams_config.app_password_encrypted,
                self.config.agent_token_encryption_key,
            )
            overlay = build_openclaw_config_overlay_teams(
                effective_model,
                self.config.agent_litellm_base_url,
            )
            secret = build_secret_teams(
                agent_id=agent.id,
                org_id=org_id,
                namespace=ns,
                msteams_app_id=app_id,
                msteams_app_password=app_password,
                msteams_tenant_id=teams_config.tenant_id,
                litellm_api_key=litellm_key,
                litellm_base_url=self.config.agent_litellm_base_url,
            )
            service = build_service(agent.id, org_id, ns, include_webhook_port=True)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported platform: {agent.platform}",
            )

        try:
            self.k8s.delete_config_map(name, ns)
            self.k8s.delete_secret(name, ns)
            self.k8s.create_config_map(
                ns,
                build_config_map(
                    agent_id=agent.id,
                    org_id=org_id,
                    namespace=ns,
                    soul_md=template.soul_md,
                    identity_md=template.identity_md,
                    user_md=template.user_md,
                    tools_md=template.tools_md,
                    agents_md=template.agents_md,
                    boot_md=template.boot_md,
                    bootstrap_md=template.bootstrap_md,
                    heartbeat_md=template.heartbeat_md,
                    openclaw_config_overlay=overlay,
                ),
            )
            self.k8s.create_secret(ns, secret)
            self.k8s.create_pvc(ns, build_pvc(agent.id, org_id, ns))
            self.k8s.create_service(ns, service)
            self.k8s.create_deployment(
                ns,
                build_deployment(
                    agent.id,
                    org_id,
                    ns,
                    self.config.agent_image,
                    self.config.agent_image_pull_secret,
                ),
            )
        except Exception:
            agent.status = AgentStatus.ERROR
            self.repository.save(agent)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start agent {agent_id}",
            )

        agent.status = AgentStatus.RUNNING
        self.repository.save(agent)
        return self._get_agent_read(agent)

    def stop_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)

        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is not running",
            )

        try:
            self.conversation_sync_service.sync_all_channels(agent_id)
        except Exception as e:
            logger.warning(
                "Conversation sync before stop failed for agent %s: %s", agent_id, e
            )

        self.sync_service.sync_agent(agent.id, org_id, force=True)
        self.k8s.delete_deployment(f"agent-{agent.id}", self.config.k8s_namespace)

        agent.status = AgentStatus.STOPPED
        self.repository.save(agent)
        return self._get_agent_read(agent)

    def delete_agent(self, agent_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        ns = self.config.k8s_namespace
        name = f"agent-{agent.id}"

        self.k8s.delete_deployment(name, ns)
        self.k8s.delete_service(name, ns)
        self.k8s.delete_pvc(name, ns)
        self.k8s.delete_secret(name, ns)
        self.k8s.delete_config_map(name, ns)

        agent.deleted_at = datetime.datetime.now(datetime.timezone.utc)
        self.repository.save(agent)

        if agent.litellm_key_encrypted:
            try:
                plaintext_key = decrypt_token(
                    agent.litellm_key_encrypted, self.config.agent_token_encryption_key
                )
                self.litellm.delete_key(plaintext_key)
            except Exception:
                logger.warning("Could not revoke LiteLLM key for agent %s", agent_id)

    def pair_agent(
        self, agent_id: UUID, data: PairRequest, context: CurrentUserContext
    ) -> str:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)

        if agent.platform != AgentPlatform.SLACK:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pairing is only supported for Slack agents",
            )

        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is not running",
            )

        ns = self.config.k8s_namespace
        name = f"agent-{agent.id}"

        pod_name = self.k8s.get_pod_name_for_deployment(name, ns)
        if not pod_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No running pod found for agent {agent_id}",
            )

        try:
            output = self.k8s.exec_command(
                pod_name,
                ns,
                ["openclaw", "pairing", "approve", data.platform, data.code],
            )
        except Exception as exc:
            logger.exception("Pairing exec failed for agent %s", agent_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to execute pairing command in agent {agent_id}",
            ) from exc

        try:
            allow_from_raw = self.k8s.exec_command(
                pod_name,
                ns,
                [
                    "cat",
                    "/home/node/.openclaw/credentials/slack-default-allowFrom.json",
                ],
            )
            paired_user_ids = json.loads(allow_from_raw).get("allowFrom", [])
            if isinstance(paired_user_ids, list):
                slack_config = self.repository.get_slack_config(agent.id)
                if slack_config:
                    existing: set[str] = set(slack_config.dm_user_ids or [])
                    paired: set[str] = {str(u) for u in paired_user_ids}
                    slack_config.dm_user_ids = list(existing | paired)
                    self.repository.save_slack_config(slack_config)
        except Exception:
            logger.warning(
                "Could not sync allowFrom for agent %s after pairing", agent_id
            )

        return output

    def list_slack_channels(
        self, agent_id: UUID, context: CurrentUserContext, search: str | None = None
    ) -> list[dict]:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        if agent.platform != AgentPlatform.SLACK:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack channels are only available for Slack agents",
            )
        return SlackClient(self._get_bot_token(agent)).search_channels(search=search)

    def list_slack_users(
        self, agent_id: UUID, context: CurrentUserContext, search: str | None = None
    ) -> list[dict]:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        if agent.platform != AgentPlatform.SLACK:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack users are only available for Slack agents",
            )
        return SlackClient(self._get_bot_token(agent)).search_users(search=search)

    def _get_bot_token(self, agent: Agent) -> str:
        slack_config = self.repository.get_slack_config(agent.id)
        if not slack_config:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Slack config missing for agent {agent.id}",
            )
        return decrypt_token(
            slack_config.bot_token_encrypted, self.config.agent_token_encryption_key
        )

    def relay_teams_webhook(
        self, agent_id: UUID, body: bytes, headers: dict[str, str]
    ) -> tuple[int, bytes, dict[str, str]]:
        agent = self.repository.get_by_id(agent_id)
        if not agent or agent.deleted_at or agent.platform != AgentPlatform.TEAMS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return self.k8s.proxy_to_agent(
            f"agent-{agent.id}",
            self.config.k8s_namespace,
            3978,
            "/api/messages",
            "POST",
            body,
            {
                "Content-Type": headers.get("content-type", "application/json"),
                "Authorization": headers.get("authorization", ""),
            },
        )

    def get_agent_health(
        self, agent_id: UUID, context: CurrentUserContext
    ) -> AgentHealthRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)

        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is not running",
            )

        name = f"agent-{agent_id}"
        ns = self.config.k8s_namespace

        pod_status = self.k8s.get_pod_readiness(name, ns)
        if pod_status == "crashed":
            return AgentHealthRead(status="crashed")
        if pod_status != "ready":
            return AgentHealthRead(status="initializing")

        try:
            data = self.k8s.fetch_agent_healthz(name, ns)
            return AgentHealthRead.model_validate(data)
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "error", "reason": "unreachable"},
            )
