import datetime
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
    build_pvc,
    build_secret,
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
    AgentRead,
    AgentStatus,
    AgentTemplate,
    AgentTemplateRead,
    AgentUpdate,
    PairRequest,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.conversations.service import ConversationSyncService
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.shared.models import PaginatedItems, Pagination

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


@inject
@singleton
@dataclass
class AgentService:
    repository: AgentRepository
    k8s: KubernetesClient
    litellm: LiteLLMClient
    config: Config
    conversation_sync_service: ConversationSyncService

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

    def create_agent(self, data: AgentCreate, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)

        agent = Agent(
            organization_id=org_id,
            name=data.name,
            slack_bot_token_encrypted=encrypt_token(
                data.slack_bot_token, self.config.agent_token_encryption_key
            ),
            slack_app_token_encrypted=encrypt_token(
                data.slack_app_token, self.config.agent_token_encryption_key
            ),
            model=data.model or "",
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

        return AgentRead.model_validate(agent)

    def get_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        return AgentRead.model_validate(agent)

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
        return self.repository.find_all_active(org_id, agent_filter, pagination)

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

        if "slack_bot_token" in updated:
            agent.slack_bot_token_encrypted = encrypt_token(
                updated["slack_bot_token"], self.config.agent_token_encryption_key
            )

        if "slack_app_token" in updated:
            agent.slack_app_token_encrypted = encrypt_token(
                updated["slack_app_token"], self.config.agent_token_encryption_key
            )

        self.repository.save(agent)
        return AgentRead.model_validate(agent)

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

        bot_token = decrypt_token(
            agent.slack_bot_token_encrypted, self.config.agent_token_encryption_key
        )
        app_token = decrypt_token(
            agent.slack_app_token_encrypted, self.config.agent_token_encryption_key
        )

        name = f"agent-{agent.id}"
        litellm_key = (
            decrypt_token(
                agent.litellm_key_encrypted, self.config.agent_token_encryption_key
            )
            if agent.litellm_key_encrypted
            else ""
        )
        effective_model = agent.model or self.config.agent_default_model
        overlay = build_openclaw_config_overlay(
            effective_model, self.config.agent_litellm_base_url
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
            self.k8s.create_secret(
                ns,
                build_secret(
                    agent_id=agent.id,
                    org_id=org_id,
                    namespace=ns,
                    slack_bot_token=bot_token,
                    slack_app_token=app_token,
                    litellm_api_key=litellm_key,
                    litellm_base_url=self.config.agent_litellm_base_url,
                ),
            )
            self.k8s.create_pvc(ns, build_pvc(agent.id, org_id, ns))
            self.k8s.create_service(ns, build_service(agent.id, org_id, ns))
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
        return AgentRead.model_validate(agent)

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

        self.k8s.delete_deployment(f"agent-{agent.id}", self.config.k8s_namespace)

        agent.status = AgentStatus.STOPPED
        self.repository.save(agent)
        return AgentRead.model_validate(agent)

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

        return output

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
        try:
            data = self.k8s.fetch_agent_healthz(name, ns)
            return AgentHealthRead.model_validate(data)
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "error", "reason": "unreachable"},
            )
