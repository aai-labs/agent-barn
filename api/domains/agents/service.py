import concurrent.futures
import datetime as dt
import fnmatch
import logging
import secrets
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient
from api.domains.agents.aai_cli_artifacts import (
    build_config_toml,
    build_env,
    build_setup_sh,
    build_tool_context_md,
    provider_to_secret_name_map,
)
from api.domains.agents.aai_cli_skills import build_skills_manifest_from_zips
from api.domains.skills.models import Skill
from api.domains.skills.repository import SkillRepository
from api.domains.agents.builders import (
    build_config_map,
    build_deployment,
    build_hermes_config,
    build_hermes_config_map,
    build_hermes_deployment,
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_teams,
    build_pvc,
    build_secret_hermes_slack,
    build_secret_slack,
    build_secret_teams,
    build_service,
)
from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    Agent,
    AgentAssignedSkillRead,
    AgentCreate,
    AgentFilter,
    AgentHealthRead,
    AgentPlatform,
    AgentRead,
    AgentSecret,
    AgentSecretCreate,
    AgentSecretRead,
    AgentSkill,
    AgentSlackConfig,
    AgentSlackConfigRead,
    AgentStatus,
    AgentTeamsConfig,
    AgentTeamsConfigRead,
    AgentType,
    AgentUpdate,
    PairRequest,
    SecretProvider,
    decrypt_content,
    encrypt_content,
    validate_content,
)
from api.domains.agents.error_messages import friendly_k8s_error, friendly_pod_reason
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.token_service import SlackConfigTokenService
from api.domains.templates.models import TemplateRead
from api.domains.templates.renderer import render_template
from api.domains.templates.repository import TemplateRepository
from api.domains.conversations.service import ConversationSyncService
from api.domains.tool_calls.sync_service import ToolCallSyncService
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.shared.models import PaginatedItems, Pagination
from api.infrastructure.integration_validators import (
    validate_bitbucket,
    validate_confluence,
    validate_github,
    validate_jira,
)
from api.infrastructure.slack.client import (
    SlackClient,
    SlackFetchError,
)
from api.infrastructure.slack.config_token import update_slack_app_name

logger = logging.getLogger(__name__)

# Bot display name cache: agent_id → (name, fetched_at). TTL = 60 s.
_bot_name_cache: dict[str, tuple[str, dt.datetime]] = {}
_BOT_NAME_TTL = dt.timedelta(seconds=60)

# Pre-stop conversation/tool-call flush is best-effort and must not block the
# teardown. We run both syncs in a shared pool and wait at most this long;
# anything still running is abandoned (the orphaned thread finishes harmlessly
# in the background). Module-level so tests can monkeypatch the budget.
_STOP_SYNC_TIMEOUT_SECONDS = 20
_stop_sync_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="agent-stop-sync"
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


_OPENROUTER_MODEL_PREFIX = "litellm/openrouter/"

_VALIDATORS: dict[SecretProvider, Any] = {
    SecretProvider.GITHUB: validate_github,
    SecretProvider.JIRA: validate_jira,
    SecretProvider.CONFLUENCE: validate_confluence,
    SecretProvider.BITBUCKET: validate_bitbucket,
}


def _allowlist_patterns(allowlist: str) -> list[str]:
    return [p.strip().lower() for p in allowlist.split(",") if p.strip()]


def filter_models_by_allowlist(catalog: list[dict], allowlist: str) -> list[dict]:
    """Keeps catalogue entries whose id matches any comma-separated glob pattern.
    An empty allowlist passes everything through. Matching is case-insensitive.
    """
    patterns = _allowlist_patterns(allowlist)
    if not patterns:
        return catalog
    return [
        model
        for model in catalog
        if any(fnmatch.fnmatch(model["id"].lower(), pattern) for pattern in patterns)
    ]


def is_model_allowed(model: str, allowlist: str) -> bool:
    """Whether a stored model string (litellm/openrouter/<slug>) is permitted by
    the allowlist globs. An empty allowlist permits everything. The litellm/
    gateway prefix is stripped so patterns match the OpenRouter slug.
    """
    patterns = _allowlist_patterns(allowlist)
    if not patterns:
        return True
    slug = model.removeprefix(_OPENROUTER_MODEL_PREFIX).lower()
    return any(fnmatch.fnmatch(slug, pattern) for pattern in patterns)


@inject
@singleton
@dataclass
class AgentService:
    repository: AgentRepository
    template_repository: TemplateRepository
    k8s: KubernetesClient
    litellm: LiteLLMClient
    openrouter: OpenRouterClient
    config: Config
    conversation_sync_service: ConversationSyncService
    sync_service: ToolCallSyncService
    skill_repository: SkillRepository
    slack_token_service: SlackConfigTokenService

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _ensure_model_allowed(self, model: str | None) -> None:
        """Rejects models outside the allowlist. litellm is cluster-internal, so
        create/update are the only paths that can set an agent's model; enforcing
        here is sufficient. An empty/None model defers to the configured default.
        """
        if model and not is_model_allowed(model, self.config.agent_model_allowlist):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model}' is not in the allowed model list",
            )

    @staticmethod
    def _build_skill_pointers(skills: list[Skill]) -> str:
        return "".join(s.tools_pointer for s in skills if s.tools_pointer)

    def _resolve_skills(
        self,
        skill_ids: list[UUID],
        secrets_data: list[AgentSecretCreate],
        org_id: UUID,
    ) -> list[Skill]:
        if not skill_ids:
            return []
        submitted_providers = {item.provider for item in secrets_data}
        accessible = {
            s.id: s for s in self.skill_repository.find_accessible_for_org(org_id)
        }
        skills = []
        for skill_id in dict.fromkeys(skill_ids):
            skill = accessible.get(skill_id)
            if skill is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )
            missing = [
                p for p in skill.required_providers if p not in submitted_providers
            ]
            if missing:
                names = ", ".join(p for p in missing)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Skill '{skill.name}' requires providers not covered "
                        f"by submitted secrets: {names}"
                    ),
                )
            skills.append(skill)
        return skills

    def _validate_skill_update(
        self,
        agent: Agent,
        data: "AgentUpdate",
        org_id: UUID,
    ) -> None:
        """Validate that new skills are accessible and that all remaining skills
        have their required providers covered after the update is applied."""
        if data.skill_ids:
            accessible = {
                s.id for s in self.skill_repository.find_accessible_for_org(org_id)
            }
            for skill_id in data.skill_ids:
                if skill_id not in accessible:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Skill {skill_id} not found",
                    )

        current_skill_rows = self.repository.get_skills_for_agent(agent.id)
        current_skill_ids = {row.skill_id for row in current_skill_rows}
        remaining_skill_ids = (current_skill_ids - set(data.removed_skill_ids)) | set(
            data.skill_ids
        )

        if not remaining_skill_ids:
            return

        current_secrets = self.repository.get_secrets_for_agent(agent.id)
        current_providers = {s.provider for s in current_secrets}
        upsert_providers = {s.provider for s in data.secrets or []}
        removed_providers = set(data.removed_secret_providers or [])
        remaining_providers = (current_providers - removed_providers) | upsert_providers

        remaining_skills = self.skill_repository.get_many_by_ids(
            list(remaining_skill_ids)
        )
        for skill in remaining_skills:
            missing = [
                p for p in skill.required_providers if p not in remaining_providers
            ]
            if missing:
                names = ", ".join(p for p in missing)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Skill '{skill.name}' requires providers that would no longer "
                        f"be available: {names}"
                    ),
                )

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
        secrets: list[AgentSecret] | None = None,
        skills: list[Skill] | None = None,
        required_skill_ids: set[UUID] | None = None,
    ) -> AgentRead:
        slack_config_read = (
            AgentSlackConfigRead.model_validate(slack_config) if slack_config else None
        )
        if slack_config_read and slack_config:
            slack_config_read.bot_display_name = self._get_bot_display_name(
                str(agent.id), slack_config
            )
        teams_config_read = (
            AgentTeamsConfigRead.model_validate(teams_config) if teams_config else None
        )
        secrets_read = [
            AgentSecretRead.model_validate(secret) for secret in (secrets or [])
        ]
        req_ids = required_skill_ids or set()
        skills_read = [
            AgentAssignedSkillRead.model_validate(skill).model_copy(
                update={"required": skill.id in req_ids}
            )
            for skill in (skills or [])
        ]
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
            agent_type=agent.agent_type,
            organization_id=agent.organization_id,
            template_slug=agent.template_slug,
            template_version=agent.template_version,
            model=agent.model,
            slack_config=slack_config_read,
            teams_config=teams_config_read,
            secrets=secrets_read,
            skills=skills_read,
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
        secrets = self.repository.get_secrets_for_agent(agent.id)
        skills = [
            s for _, s in self.skill_repository.get_agent_skills_with_details(agent.id)
        ]
        template = self.template_repository.get_template_by_slug_and_version(
            agent.organization_id, agent.template_slug, agent.template_version
        )
        required_ids = (
            self.template_repository.get_required_skill_ids(template.id)
            if template
            else set()
        )
        return self._build_agent_read(
            agent, slack_config, teams_config, secrets, skills, required_ids
        )

    def _get_bot_display_name(
        self, agent_id: str, slack_config: AgentSlackConfig
    ) -> str | None:
        now = dt.datetime.now(dt.timezone.utc)
        cached = _bot_name_cache.get(agent_id)
        if cached and now - cached[1] < _BOT_NAME_TTL:
            return cached[0]
        try:
            bot_token = decrypt_token(
                slack_config.bot_token_encrypted,
                self.config.agent_token_encryption_key,
            )
            info = SlackClient(bot_token).get_bot_info()
            name = info.get("bot_name") or None
            if name:
                _bot_name_cache[agent_id] = (name, now)
            return name
        except Exception:
            return cached[0] if cached else None

    def create_agent(self, data: AgentCreate, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        self._ensure_model_allowed(data.model)

        if data.platform == AgentPlatform.SLACK:
            assert data.slack_bot_token is not None
            assert data.slack_app_token is not None
            ok, reason = self._check_slack_tokens(
                data.slack_bot_token, data.slack_app_token
            )
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=reason
                )

        # Pin to the requested version, or the lineage's latest if unspecified.
        if data.template_version is not None:
            template = self.template_repository.get_template_by_slug_and_version(
                org_id, data.template_slug, data.template_version
            )
            missing_detail = (
                f"Template {data.template_slug} v{data.template_version} not found"
            )
        else:
            template = self.template_repository.get_latest_template(
                org_id, data.template_slug
            )
            missing_detail = f"Template {data.template_slug} not found"
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail
            )

        agent = Agent(
            organization_id=org_id,
            name=data.name,
            model=data.model or "",
            platform=data.platform,
            agent_type=data.agent_type,
            template_slug=template.template_slug,
            template_version=template.version,
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

        self.repository.save(agent)

        slack_config = None
        teams_config = None

        if data.platform == AgentPlatform.SLACK:
            slack_config = AgentSlackConfig(
                agent_id=agent.id,
                bot_token_encrypted=encrypt_token(
                    cast(str, data.slack_bot_token),
                    self.config.agent_token_encryption_key,
                ),
                app_token_encrypted=encrypt_token(
                    cast(str, data.slack_app_token),
                    self.config.agent_token_encryption_key,
                ),
                channel_ids=data.slack_channel_ids,
                dm_user_ids=data.slack_dm_user_ids,
                group_policy=data.slack_group_policy,
                dm_policy=data.slack_dm_policy,
            )
            self.repository.save_slack_config(slack_config)
        elif data.platform == AgentPlatform.TEAMS:
            assert data.teams_app_id is not None
            assert data.teams_app_password is not None
            assert data.teams_tenant_id is not None
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
                tenant_id=data.teams_tenant_id,
            )
            self.repository.save_teams_config(teams_config)

        # Integration secrets are platform-independent. Persist them before any
        # Teams auto-start so they exist if/when the pod is later built.
        secrets: list[AgentSecret] = []
        for item in data.secrets:
            content = validate_content(item.provider, item.content)
            saved = self.repository.save_secret(
                AgentSecret(
                    agent_id=agent.id,
                    provider=item.provider,
                    secret_name=PROVIDER_DISPLAY_NAMES[item.provider],
                    content=encrypt_content(
                        content, self.config.agent_token_encryption_key
                    ),
                )
            )
            secrets.append(saved)

        # Validate that all template-required skills are present in the request.
        required_ids = self.template_repository.get_required_skill_ids(template.id)
        if required_ids:
            missing = required_ids - set(data.skill_ids)
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Required template skills must be included in skill_ids",
                )

        # Resolve and validate skills before any DB writes.
        skills_to_assign = self._resolve_skills(data.skill_ids, data.secrets, org_id)

        if skills_to_assign:
            self.repository.save_skills(
                [AgentSkill(agent_id=agent.id, skill_id=s.id) for s in skills_to_assign]
            )

        if data.platform == AgentPlatform.TEAMS:
            return self.start_agent(agent.id, context)
        return self._build_agent_read(
            agent, slack_config, teams_config, secrets, skills_to_assign, required_ids
        )

    def get_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        return self._get_agent_read(agent)

    def get_agent_template(
        self, agent_id: UUID, version: int, context: CurrentUserContext
    ) -> TemplateRead:
        org_id = self._org_id(context)
        agent = self._get_active_or_404(agent_id, org_id)
        template = self.template_repository.get_template_by_slug_and_version(
            org_id, agent.template_slug, version
        )
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template version {version} not found for agent {agent_id}",
            )
        return TemplateRead.model_validate(template)

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
        secrets_by_agent = self.repository.get_secrets_for_agents(agent_ids)
        skills_by_agent = self.skill_repository.get_skills_for_agents(agent_ids)

        slug_versions = list({(a.template_slug, a.template_version) for a in agents})
        template_id_map = self.template_repository.get_template_ids_for_slug_versions(
            org_id, slug_versions
        )
        template_ids = list(template_id_map.values())
        req_ids_by_template = (
            self.template_repository.get_required_skill_ids_for_templates(template_ids)
        )

        def _required_ids(agent: Agent) -> set[UUID]:
            tid = template_id_map.get((agent.template_slug, agent.template_version))
            return req_ids_by_template.get(tid, set()) if tid else set()

        items = [
            self._build_agent_read(
                agent,
                slack_configs.get(agent.id),
                teams_configs.get(agent.id),
                secrets_by_agent.get(agent.id, []),
                skills_by_agent.get(agent.id, []),
                _required_ids(agent),
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

        # Re-pin the agent to a different template (slug, version). The model
        # validator guarantees both keys appear together.
        effective_template = None
        if "template_slug" in updated:
            effective_template = (
                self.template_repository.get_template_by_slug_and_version(
                    org_id, updated["template_slug"], updated["template_version"]
                )
            )
            if effective_template is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        f"Template {updated['template_slug']} "
                        f"v{updated['template_version']} not found"
                    ),
                )
            agent.template_slug = effective_template.template_slug
            agent.template_version = effective_template.version

        if "name" in updated:
            agent.name = updated["name"]
            if agent.platform == AgentPlatform.SLACK:
                self._try_rename_slack_app(agent, updated["name"], context)

        if "model" in updated:
            self._ensure_model_allowed(updated["model"])
            agent.model = updated["model"]

        # Slack config updates
        if agent.platform == AgentPlatform.SLACK and (
            _SLACK_CONFIG_FIELDS & updated.keys()
        ):
            ok, reason = self._check_slack_tokens(
                bot_token=updated.get("slack_bot_token"),
                app_token=updated.get("slack_app_token"),
            )
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=reason
                )

            slack_config = self.repository.get_slack_config(agent.id)
            if slack_config:
                if "slack_bot_token" in updated:
                    slack_config.bot_token_encrypted = encrypt_token(
                        updated["slack_bot_token"],
                        self.config.agent_token_encryption_key,
                    )
                    _bot_name_cache.pop(str(agent.id), None)
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
                if "slack_channel_ids" in updated:
                    self._join_public_channels(
                        self._get_bot_token(agent), updated["slack_channel_ids"]
                    )

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

        # Validate skill changes against the effective template's required skills.
        if effective_template is None:
            effective_template = (
                self.template_repository.get_template_by_slug_and_version(
                    org_id, agent.template_slug, agent.template_version
                )
            )
        required_ids = (
            self.template_repository.get_required_skill_ids(effective_template.id)
            if effective_template
            else set()
        )
        if required_ids:
            # Block removal of required skills.
            if data.removed_skill_ids:
                blocked = required_ids & set(data.removed_skill_ids)
                if blocked:
                    blocked_skills = self.skill_repository.get_many_by_ids(
                        list(blocked)
                    )
                    names = ", ".join(s.name for s in blocked_skills)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot remove skills required by the template: {names}",
                    )
            # When re-pinning, validate that required skills will be present.
            if "template_slug" in updated:
                existing_skill_ids = {
                    s.id
                    for _, s in self.skill_repository.get_agent_skills_with_details(
                        agent.id
                    )
                }
                effective_skill_ids = (existing_skill_ids | set(data.skill_ids)) - set(
                    data.removed_skill_ids
                )
                if required_ids - effective_skill_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Required template skills must be included in skill_ids",
                    )

        # Validate skills accessibility and secret coverage
        if data.skill_ids or data.removed_secret_providers:
            self._validate_skill_update(agent, data, org_id)

        # Integration secrets: platform-independent. Remove first, then upsert
        # (the AgentUpdate validator already forbids a provider in both lists).
        # Validate and encrypt all upserts before touching the DB so that a
        # validation failure never leaves already-deleted secrets permanently gone.
        if "removed_secret_providers" in updated or "secrets" in updated:
            key = self.config.agent_token_encryption_key
            upserts: list[tuple[AgentSecretCreate, str]] = [
                (
                    item,
                    encrypt_content(validate_content(item.provider, item.content), key),
                )
                for item in data.secrets or []
            ]
            for provider in updated.get("removed_secret_providers") or []:
                self.repository.delete_secret(agent.id, provider)
            for item, encrypted in upserts:
                existing = self.repository.get_secret(agent.id, item.provider)
                if existing:
                    existing.content = encrypted
                    existing.secret_name = PROVIDER_DISPLAY_NAMES[item.provider]
                    self.repository.save_secret(existing)
                else:
                    self.repository.save_secret(
                        AgentSecret(
                            agent_id=agent.id,
                            provider=item.provider,
                            secret_name=PROVIDER_DISPLAY_NAMES[item.provider],
                            content=encrypted,
                        )
                    )

        # Apply skill changes
        for skill_id in data.removed_skill_ids:
            self.repository.remove_skill(agent.id, skill_id)
        for skill_id in dict.fromkeys(data.skill_ids):
            self.repository.add_skill(agent.id, skill_id)

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

        template = self.template_repository.get_template_or_raise(
            org_id, agent.template_slug, agent.template_version
        )
        # Placeholders are kept raw in storage and rendered at seed time.
        rendered = render_template(template, agent.name)
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
        overlay: dict | None = None
        hermes_cfg: dict | None = None

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
            ok, reason = self._check_slack_tokens(
                bot_token=bot_token, app_token=app_token
            )
            if not ok:
                agent.last_error = reason
                agent.status = AgentStatus.ERROR
                self.repository.save(agent)
                return self._get_agent_read(agent)

            if slack_config.channel_ids:
                self._join_public_channels(bot_token, slack_config.channel_ids)
            service = build_service(agent.id, org_id, ns)

            if agent.agent_type == AgentType.HERMES:
                api_server_key = secrets.token_urlsafe(32)
                hermes_cfg = build_hermes_config(
                    effective_model,
                    self.config.agent_litellm_base_url,
                    dm_policy=str(slack_config.dm_policy),
                    group_policy=str(slack_config.group_policy),
                )
                secret = build_secret_hermes_slack(
                    agent_id=agent.id,
                    org_id=org_id,
                    namespace=ns,
                    agent_name=agent.name,
                    slack_bot_token=bot_token,
                    slack_app_token=app_token,
                    litellm_api_key=litellm_key,
                    litellm_base_url=self.config.agent_litellm_base_url,
                    api_server_key=api_server_key,
                    channel_ids=slack_config.channel_ids,
                    dm_user_ids=slack_config.dm_user_ids,
                    dm_policy=str(slack_config.dm_policy),
                )
                deployment = build_hermes_deployment(
                    agent.id,
                    org_id,
                    ns,
                    self.config.hermes_image,
                    self.config.agent_image_pull_secret,
                )
            else:
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
                deployment = build_deployment(
                    agent.id,
                    org_id,
                    ns,
                    self.config.openclaw_image,
                    self.config.agent_image_pull_secret,
                )
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
            deployment = build_deployment(
                agent.id,
                org_id,
                ns,
                self.config.openclaw_image,
                self.config.agent_image_pull_secret,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported platform: {agent.platform}",
            )

        # aai-cli integration secrets — all agent types.
        agent_secrets = self.repository.get_secrets_for_agent(agent.id)
        decrypted = {
            SecretProvider(s.provider): decrypt_content(
                SecretProvider(s.provider),
                s.content,
                self.config.agent_token_encryption_key,
            )
            for s in agent_secrets
        }
        store = {
            p: c for p, c in decrypted.items() if p.value in provider_to_secret_name_map
        }
        aai_home = "/opt/data" if agent.agent_type == AgentType.HERMES else "/home/node"
        aai_config_toml = (
            build_config_toml(decrypted, home_dir=aai_home) if decrypted else None
        )
        aai_setup_sh = (
            build_setup_sh(list(store), home_dir=aai_home) if decrypted else None
        )
        if store:
            secret.string_data.update(build_env(store))

        agent_skills = self.skill_repository.get_agent_skills_with_details(agent.id)
        skills_json = (
            build_skills_manifest_from_zips(agent_skills) if agent_skills else None
        )
        tools_md = (
            rendered.tools_md
            + self._build_skill_pointers([s for _, s in agent_skills])
            + build_tool_context_md(decrypted)
        )

        if agent.agent_type == AgentType.HERMES:
            assert hermes_cfg is not None
            config_map = build_hermes_config_map(
                agent_id=agent.id,
                org_id=org_id,
                namespace=ns,
                soul_md=rendered.soul_md,
                identity_md=rendered.identity_md,
                user_md=rendered.user_md,
                tools_md=tools_md,
                agents_md=rendered.agents_md,
                boot_md=rendered.boot_md,
                heartbeat_md=rendered.heartbeat_md,
                hermes_config=hermes_cfg,
                aai_cli_config_toml=aai_config_toml,
                aai_cli_setup_sh=aai_setup_sh,
                skills_json=skills_json,
            )
        else:
            config_map = build_config_map(
                agent_id=agent.id,
                org_id=org_id,
                namespace=ns,
                soul_md=rendered.soul_md,
                identity_md=rendered.identity_md,
                user_md=rendered.user_md,
                tools_md=tools_md,
                agents_md=rendered.agents_md,
                boot_md=rendered.boot_md,
                bootstrap_md=rendered.bootstrap_md,
                heartbeat_md=rendered.heartbeat_md,
                openclaw_config_overlay=overlay,
                aai_cli_config_toml=aai_config_toml,
                aai_cli_setup_sh=aai_setup_sh,
                skills_json=skills_json,
            )

        try:
            self.k8s.delete_config_map(name, ns)
            self.k8s.delete_secret(name, ns)
            self.k8s.create_config_map(ns, config_map)
            self.k8s.create_secret(ns, secret)
            self.k8s.create_pvc(
                ns,
                build_pvc(agent.id, org_id, ns, self.config.storage_class or None),
            )
            self.k8s.create_service(ns, service)
            self.k8s.create_deployment(ns, deployment)
        except Exception as exc:
            logger.exception("Failed to start agent %s", agent_id)
            agent.status = AgentStatus.ERROR
            agent.last_error = friendly_k8s_error(exc)
            self.repository.save(agent)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start agent {agent_id}",
            )

        agent.status = AgentStatus.RUNNING
        agent.last_error = None
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

        # Best-effort flush of conversation + tool-call state before teardown,
        # bounded so a rate-limited/slow Slack can never block the stop. Both
        # syncs run concurrently and share one timeout budget; whatever doesn't
        # finish in time is abandoned and teardown proceeds regardless.
        futures = {
            _stop_sync_pool.submit(
                self.conversation_sync_service.sync_all_channels, agent_id
            ): "conversation sync",
            _stop_sync_pool.submit(
                self.sync_service.sync_agent, agent.id, org_id, force=True
            ): "tool-call sync",
        }
        done, not_done = concurrent.futures.wait(
            futures, timeout=_STOP_SYNC_TIMEOUT_SECONDS
        )
        for fut in done:
            exc = fut.exception()
            if exc is not None:
                logger.warning(
                    "%s before stop failed for agent %s: %s",
                    futures[fut],
                    agent_id,
                    exc,
                )
        for fut in not_done:
            logger.warning(
                "%s exceeded %ss during stop of agent %s; proceeding with teardown",
                futures[fut],
                _STOP_SYNC_TIMEOUT_SECONDS,
                agent_id,
            )

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

        agent.deleted_at = dt.datetime.now(dt.timezone.utc)
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

        if agent.agent_type == AgentType.HERMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pairing is not supported for Hermes agents",
            )
        if agent.platform in (AgentPlatform.SLACK, AgentPlatform.TEAMS):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pairing is not supported for this platform",
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

        return output

    def _check_slack_tokens(
        self, bot_token: str | None = None, app_token: str | None = None
    ) -> tuple[bool, str]:
        """Validates whichever tokens are provided. Always ok when skip_slack_token_validation is set."""
        if self.config.skip_slack_token_validation:
            return True, ""
        client = SlackClient(bot_token or "", app_token=app_token)
        if bot_token is not None:
            ok, reason = client.validate_bot_token()
            if not ok:
                return ok, reason
        if app_token is not None:
            ok, reason = client.validate_app_token()
            if not ok:
                return ok, reason
        return True, ""

    def _join_public_channels(self, bot_token: str, channel_ids: list[str]) -> None:
        client = SlackClient(bot_token)
        for channel_id in channel_ids:
            try:
                client.join_channel(channel_id)
            except Exception as e:
                logger.warning("Unexpected error joining channel %s: %s", channel_id, e)

    def list_models(self, context: CurrentUserContext) -> list[dict]:
        """Returns the allowlisted OpenRouter models as picker options. The
        configured default (AGENT_DEFAULT_MODEL) is guaranteed present, flagged
        is_default, and listed first so the frontend and backend agree on it.
        """
        self._org_id(context)
        catalog = self.openrouter.list_models()
        allowed = filter_models_by_allowlist(catalog, self.config.agent_model_allowlist)
        options = [
            {
                "value": f"litellm/openrouter/{model['id']}",
                "label": model["name"],
                "context_length": model.get("context_length"),
                "pricing": model.get("pricing"),
            }
            for model in allowed
        ]

        default_value = self.config.agent_default_model
        if default_value and not any(o["value"] == default_value for o in options):
            options.insert(
                0,
                {
                    "value": default_value,
                    "label": default_value.removeprefix(_OPENROUTER_MODEL_PREFIX),
                    "context_length": None,
                    "pricing": None,
                },
            )

        # Stable sort puts the default first while preserving catalogue order.
        options.sort(key=lambda o: o["value"] != default_value)
        for option in options:
            option["is_default"] = option["value"] == default_value
        return options

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
        try:
            return SlackClient(self._get_bot_token(agent)).list_channels(search=search)
        except SlackFetchError as exc:
            logger.warning(
                "Failed to list Slack channels for agent %s: %s", agent_id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not load Slack channels right now. Please try again.",
            ) from exc

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
        try:
            return SlackClient(self._get_bot_token(agent)).list_users(search=search)
        except SlackFetchError as exc:
            logger.warning("Failed to list Slack users for agent %s: %s", agent_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not load Slack users right now. Please try again.",
            ) from exc

    def validate_integration(
        self, agent_id: UUID, provider: SecretProvider, context: CurrentUserContext
    ) -> dict:
        """Validate an existing secret on demand. Never persists — returns result directly."""
        org_id = self._org_id(context)
        self._get_active_or_404(agent_id, org_id)
        secret = self.repository.get_secret(agent_id, provider)
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {provider.value} credential configured for this agent",
            )
        validator = _VALIDATORS.get(provider)
        if validator is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No validator available for {provider.value}",
            )
        content = decrypt_content(
            provider, secret.content, self.config.agent_token_encryption_key
        )
        result = validator(content)  # type: ignore[arg-type]
        if result.valid and result.missing_scopes:
            validation_status = "warning"
        elif result.valid:
            validation_status = "valid"
        else:
            validation_status = "invalid"
        return {
            "validation_status": validation_status,
            "validation_identity": result.identity,
            "validation_error": result.error,
            "missing_scopes": result.missing_scopes,
        }

    def _try_rename_slack_app(
        self, agent: Agent, new_name: str, context: CurrentUserContext
    ) -> None:
        """Best-effort: rename the Slack app to match the new agent name. Never raises."""
        try:
            bot_token = self._get_bot_token(agent)
            bot_info = SlackClient(bot_token).get_bot_info()
            app_id = bot_info.get("app_id", "")
            if not app_id:
                return
            access_token = self.slack_token_service.get_usable_access_token(
                context.user.id
            )
            update_slack_app_name(access_token, app_id, new_name)
        except Exception:
            logger.warning(
                "Could not rename Slack app for agent %s to %r",
                agent.id,
                new_name,
                exc_info=True,
            )

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

        if agent.status == AgentStatus.ERROR:
            return AgentHealthRead(status="error", reason=agent.last_error)

        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is not running",
            )

        name = f"agent-{agent_id}"
        ns = self.config.k8s_namespace

        pod_status, pod_reason = self.k8s.get_pod_readiness(name, ns)
        if pod_status == "crashed":
            return AgentHealthRead(
                status="crashed", reason=friendly_pod_reason(pod_reason)
            )
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
