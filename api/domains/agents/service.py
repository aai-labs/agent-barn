import datetime as dt
import fnmatch
import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.aai_cli_artifacts import (
    PROFILE_SLUGS,
    build_config_toml,
    build_env,
    build_integrations_policy_md,
    build_local_tools_policy_md,
    build_setup_sh,
    build_tool_context_md,
    provider_secrets_map,
)
from api.domains.agents.aai_cli_skills import build_skills_manifest
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.builders import (
    build_config_map,
    build_deployment,
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
    build_openclaw_gateway_config,
    build_pvc,
    build_secret_hermes_runtime,
    build_secret_runtime,
    build_service,
)
from api.domains.agents.error_messages import friendly_k8s_error, friendly_pod_reason
from api.domains.agents.gog_artifacts import build_gog_env, build_gog_policy_md, build_gog_setup_sh
from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    Agent,
    AgentAssignedSkillRead,
    AgentConfigurationRead,
    AgentConfigurationVersionRead,
    AgentCreate,
    AgentFilter,
    AgentHealthRead,
    AgentLogHistoryRead,
    AgentLogSnapshot,
    AgentLogsRead,
    AgentOverrideAuthorRead,
    AgentRead,
    AgentSecret,
    AgentSecretCreate,
    AgentSecretRead,
    AgentSkill,
    AgentStatus,
    AgentTemplateOverrideDraft,
    AgentTemplateOverrideDraftRead,
    AgentTemplateOverrideDraftUpdate,
    AgentTemplateOverridePublish,
    AgentTemplateOverrideRequiredSkillRead,
    AgentTemplateOverrideSourceType,
    AgentTemplateOverrideVersion,
    AgentTemplateOverrideVersionRead,
    AgentTemplatePinType,
    AgentTemplateSelection,
    AgentType,
    AgentUpdate,
    CommandApprovalMode,
    ConfluenceContent,
    FirecrawlContent,
    GoogleWorkspaceContent,
    JiraContent,
    SecretProvider,
    SkillVersionPin,
    decrypt_content,
    encrypt_content,
    validate_content,
)
from api.domains.agents.override_repository import (
    AgentOverrideConcurrencyError,
    AgentOverrideRepository,
    AgentOverrideSnapshot,
)
from api.domains.agents.repository import AgentRepository
from api.domains.agents.runtime_policy import build_chat_commands_policy_md, build_role_scope_policy_md
from api.domains.auth.models import CurrentUserContext
from api.domains.events import ActorIdentity, ActorIdentityType, EventDeliveryDispatcher, resolve_actor_identity
from api.domains.events.catalog import (
    AGENT_SECRET_ADDED,
    AGENT_SECRET_UPDATED,
    AGENT_STARTED,
    AGENT_STOPPED,
)
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.shared_credentials.repository import SharedCredentialRepository
from api.domains.skills.models import PinnedSkill, Skill, derive_tools_pointer
from api.domains.skills.repository import SkillRepository
from api.domains.templates.models import AgentTemplate, PlatformTemplate, TemplateRead
from api.domains.templates.renderer import render_template
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.requirements import effective_required_ids, split_requirements
from api.domains.users.models import User
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.integration_validators import (
    PROVIDER_VALIDATORS,
    format_validation_result,
)
from api.infrastructure.integration_validators.atlassian_utils import (
    get_atlassian_cloud_id,
)
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_CREDENTIAL_FIELDS = frozenset(
    {
        "secrets",
        "shared_credentials",
        "removed_secret_providers",
    }
)


_MAX_LOG_SNAPSHOT_BYTES = 1_048_576  # 1 MB

_OPENROUTER_MODEL_PREFIX = "litellm/openrouter/"


def _enrich_atlassian_content(content: Any) -> Any:
    """For Atlassian integrations using scoped API tokens, fetch and store the cloud_id.

    Scoped tokens still use Basic Auth, but must be sent to the API Gateway URL
    (https://api.atlassian.com/ex/jira/<cloud_id>) instead of the site URL directly.
    Best-effort: if the lookup fails, the content is returned unchanged.
    """
    if isinstance(content, JiraContent) and content.use_scoped_token and not content.cloud_id:
        cloud_id, cloud_err = get_atlassian_cloud_id(content.site_url)
        if cloud_id:
            return content.model_copy(update={"cloud_id": cloud_id})
        else:
            logger.warning(f"Failed to fetch Jira cloud_id for {content.site_url}: {cloud_err}")
    elif isinstance(content, ConfluenceContent) and content.use_scoped_token and not content.cloud_id:
        cloud_id, cloud_err = get_atlassian_cloud_id(content.site_url)
        if cloud_id:
            return content.model_copy(update={"cloud_id": cloud_id})
        else:
            logger.warning(f"Failed to fetch Confluence cloud_id for {content.site_url}: {cloud_err}")
    return content


def filter_models_by_allowlist(catalog: list[dict], allowlist: list[str]) -> list[dict]:
    """Keeps catalogue entries whose id matches any glob pattern in the allowlist.
    An empty allowlist blocks everything. Matching is case-insensitive.
    """
    if not allowlist:
        return []
    patterns = [p.strip().lower() for p in allowlist if p.strip()]
    if not patterns:
        return []
    return [model for model in catalog if any(fnmatch.fnmatch(model["id"].lower(), pattern) for pattern in patterns)]


def is_model_allowed(model: str, allowlist: list[str]) -> bool:
    """Whether a stored model string (litellm/openrouter/<slug>) is permitted by
    the allowlist globs. An empty allowlist blocks everything. The litellm/
    gateway prefix is stripped so patterns match the OpenRouter slug.
    """
    if not allowlist:
        return False
    patterns = [p.strip().lower() for p in allowlist if p.strip()]
    if not patterns:
        return False
    slug = model.removeprefix(_OPENROUTER_MODEL_PREFIX).lower()
    return any(fnmatch.fnmatch(slug, pattern) for pattern in patterns)


@inject
@singleton
@dataclass
class AgentService:
    repository: AgentRepository
    override_repository: AgentOverrideRepository
    authorization: AgentAuthorization
    template_repository: TemplateRepository
    k8s: KubernetesClient
    litellm: LiteLLMClient
    openrouter: OpenRouterClient
    config: Config
    skill_repository: SkillRepository
    shared_credential_repository: SharedCredentialRepository
    event_delivery_dispatcher: EventDeliveryDispatcher
    organization_lookup: OrganizationLookupService
    agent_settings_lookup: AgentSettingsLookupService

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    @staticmethod
    def _set_pin(agent: Agent, template: AgentTemplate | PlatformTemplate) -> None:
        """Point an agent at a resolved template via the right mutually-exclusive FK."""
        agent.agent_template_override_version_id = None
        if isinstance(template, PlatformTemplate):
            agent.platform_template_id = template.id
            agent.agent_template_id = None
        else:
            agent.agent_template_id = template.id
            agent.platform_template_id = None

    def count_agents_in_error(self) -> int:
        return self.repository.count_agents_in_error()

    def count_agents_for_stats(self, **filters) -> tuple[int, int, int, int]:
        """(total, running, stopped, errored) Agent counts for the stats surfaces (AF-256).
        Authority is enforced at the platform route; passing organization_id
        narrows the same aggregate for a future Organization dashboard."""
        return self.repository.count_agents_for_stats(**filters)

    def agent_inventory(
        self, window_start: dt.datetime, window_end: dt.datetime, **kwargs
    ) -> list[tuple[dt.datetime, int, int]]:
        """(bucket_start, existing, created) Agent inventory (AF-256)."""
        return self.repository.agent_inventory_since(window_start, window_end, **kwargs)

    def _ensure_model_allowed(self, model: str | None, org_id: UUID) -> None:
        """Rejects models outside the allowlist. litellm is cluster-internal, so
        create/update are the only paths that can set an agent's model; enforcing
        here is sufficient. An empty/None model defers to the resolved default.

        The resolved default is admitted whatever the allowlist says. When the
        Organization set its own default that is already true by invariant; the case
        this covers is an Organization following a platform default its allowlist
        does not cover, where the model picker offers that default and rejecting it
        would make the one pre-selected option unsavable.
        """
        if model:
            allowed_models = self.organization_lookup.get_allowed_models(org_id)
            if allowed_models is None:
                raise HTTPException(status_code=404, detail="Organization not found")
            if is_model_allowed(model, allowed_models):
                return
            if model == self.agent_settings_lookup.resolve_default_model(org_id):
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model}' is not in the allowed model list",
            )

    @staticmethod
    def _ensure_approval_mode_supported(agent_type: AgentType, approval_mode: CommandApprovalMode | None) -> None:
        """OpenClaw has no user-configurable command-approval control; only Hermes
        maps approval_mode onto a runtime policy (see builders/hermes.py). An
        omitted value defers to the AgentCreate/AgentUpdate default of AUTO, which
        is a no-op for OpenClaw, but an explicit non-AUTO value would silently
        have no effect, so it is rejected rather than accepted and ignored.
        """
        if agent_type == AgentType.OPENCLAW and approval_mode is not None and approval_mode != CommandApprovalMode.AUTO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OpenClaw does not support command approval; approval_mode is Hermes-only.",
            )

    @staticmethod
    def _build_skill_pointers(skills: list[Skill]) -> str:
        return "".join(derive_tools_pointer(s) for s in skills)

    def _auto_attached_aai_cli_skills(
        self,
        configured_providers: set[SecretProvider],
        already_assigned_ids: set[UUID],
    ) -> list[Skill]:
        """aai-cli skills whose required providers are all configured.

        Configuring a provider secret implicitly mounts its aai-cli skill (docs +
        tools pointer) at start time, so an agent can use a configured integration
        even when the skill was not explicitly assigned. Skills already explicitly
        assigned are skipped to avoid duplicate mounts.
        """
        if not configured_providers:
            return []
        return [
            skill
            for skill in self.skill_repository.get_aai_cli_skills()
            if skill.id not in already_assigned_ids
            and skill.required_providers
            and all(p in configured_providers for p in skill.required_providers)
        ]

    def _remaining_skills(
        self,
        agent_id: UUID,
        added_skill_ids: list[UUID],
        removed_skill_ids: list[UUID],
    ) -> list[Skill]:
        """Skills the agent would have after applying the given add/remove sets."""
        current_skill_rows = self.repository.get_skills_for_agent(agent_id)
        current_skill_ids = {row.skill_id for row in current_skill_rows}
        remaining_skill_ids = (current_skill_ids - set(removed_skill_ids)) | set(added_skill_ids)
        if not remaining_skill_ids:
            return []
        return self.skill_repository.get_many_by_ids(list(remaining_skill_ids))

    def _resolve_skills(
        self,
        skill_ids: list[UUID],
        secrets_data: list[AgentSecretCreate],
        org_id: UUID,
        extra_providers: set[SecretProvider] | None = None,
    ) -> list[Skill]:
        if not skill_ids:
            return []
        submitted_providers = {item.provider for item in secrets_data}
        if extra_providers:
            submitted_providers |= extra_providers
        accessible = {s.id: s for s in self.skill_repository.find_accessible_for_org(org_id)}
        skills = []
        for skill_id in dict.fromkeys(skill_ids):
            skill = accessible.get(skill_id)
            if skill is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )
            missing = [p for p in skill.required_providers if p not in submitted_providers]
            if missing:
                names = ", ".join(p for p in missing)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Skill '{skill.name}' requires providers not covered by submitted secrets: {names}"),
                )
            skills.append(skill)
        return skills

    def _resolve_skill_pins(
        self,
        skill_ids: list[UUID],
        pins: list[SkillVersionPin],
        current_skill_ids: set[UUID],
        removed_skill_ids: list[UUID],
        org_id: UUID,
    ) -> list[SkillVersionPin]:
        """Resolve every agent assignment to an explicit pinned version.

        Added skills pin to a requested version when given, else to the skill's
        latest at apply time. Existing skills can be re-pinned through the same
        ``pins`` list. Every pin must reference a skill the agent ends up with,
        and the requested version must exist (it can later be deleted only after
        no agent pins it, so a valid pin never dangles from version deletion).
        """
        overlap = set(skill_ids) & set(removed_skill_ids)
        if overlap:
            ids = ", ".join(str(skill_id) for skill_id in sorted(overlap, key=str))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Skill ID(s) cannot be both added and removed: {ids}",
            )

        pin_map: dict[UUID, SkillVersionPin] = {}
        for pin in pins:
            if pin.skill_id in pin_map:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Duplicate skill version pin for skill {pin.skill_id}",
                )
            pin_map[pin.skill_id] = pin
        remaining_ids = current_skill_ids - set(removed_skill_ids)
        allowed_ids = remaining_ids | set(skill_ids)
        extras = set(pin_map) - allowed_ids
        if extras:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Skill version pins must reference a skill the agent ends up with",
            )

        requested_ids = set(skill_ids) | set(pin_map)
        if requested_ids:
            accessible_ids = {skill.id for skill in self.skill_repository.find_accessible_for_org(org_id)}
            inaccessible_ids = requested_ids - accessible_ids
            if inaccessible_ids:
                skill_id = min(inaccessible_ids, key=str)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )

        resolved: list[SkillVersionPin] = []
        resolved_ids: set[UUID] = set()
        for skill_id in dict.fromkeys(skill_ids):
            pin = pin_map.get(skill_id)
            if pin is None:
                latest = self.skill_repository.get_latest_version(skill_id)
                pin = SkillVersionPin(skill_id=skill_id, version=latest.version if latest else 1)
            else:
                if self.skill_repository.get_version(skill_id, pin.version) is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Version {pin.version} not found for skill {skill_id}",
                    )
            resolved.append(pin)
            resolved_ids.add(skill_id)
        for pin in pins:
            if pin.skill_id in current_skill_ids and pin.skill_id not in resolved_ids:
                if self.skill_repository.get_version(pin.skill_id, pin.version) is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Version {pin.version} not found for skill {pin.skill_id}",
                    )
                resolved.append(pin)
                resolved_ids.add(pin.skill_id)
        return resolved

    def _validate_skill_update(
        self,
        agent: Agent,
        data: AgentUpdate,
        org_id: UUID,
    ) -> None:
        """Validate that new skills are accessible and that all remaining skills
        have their required providers covered after the update is applied."""
        if data.skill_ids:
            accessible = {s.id for s in self.skill_repository.find_accessible_for_org(org_id)}
            for skill_id in data.skill_ids:
                if skill_id not in accessible:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Skill {skill_id} not found",
                    )

        remaining_skills = self._remaining_skills(agent.id, data.skill_ids, data.removed_skill_ids)
        if not remaining_skills:
            return

        current_secrets = self.repository.get_secrets_for_agent(agent.id)
        current_providers = {s.provider for s in current_secrets}
        upsert_providers = {s.provider for s in data.secrets or []}
        removed_providers = set(data.removed_secret_providers or [])
        shared_attach_providers: set[str] = set()
        if data.shared_credentials:
            shared_creds = self.shared_credential_repository.get_by_ids_and_org(
                [sc.shared_credential_id for sc in data.shared_credentials], org_id
            )
            shared_attach_providers = {c.provider for c in shared_creds}
        remaining_providers = (current_providers - removed_providers) | upsert_providers | shared_attach_providers
        for skill in remaining_skills:
            missing = [p for p in skill.required_providers if p not in remaining_providers]
            if missing:
                names = ", ".join(p for p in missing)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Skill '{skill.name}' requires providers that would no longer be available: {names}"),
                )

    def _build_agent_read(
        self,
        agent: Agent,
        secrets: list[AgentSecret] | None = None,
        skills: list[PinnedSkill] | None = None,
        required_skill_map: dict[UUID, str | None] | None = None,
        allowed_actions: list[PermissionKey] | None = None,
        template_key: str = "",
        template_version: int = 0,
        template_pin_type: AgentTemplatePinType = AgentTemplatePinType.SHARED,
        override_version: int | None = None,
        effective_default_model: str = "",
    ) -> AgentRead:
        shared_ids = [s.shared_credential_id for s in (secrets or []) if s.shared_credential_id is not None]
        shared_creds_by_id = {}
        if shared_ids:
            shared_creds = self.shared_credential_repository.get_by_ids_and_org(shared_ids, agent.organization_id)
            shared_creds_by_id = {c.id: c for c in shared_creds}
        secrets_read = []
        for secret in secrets or []:
            read = AgentSecretRead.model_validate(secret)
            if secret.shared_credential_id and secret.shared_credential_id in shared_creds_by_id:
                sc = shared_creds_by_id[secret.shared_credential_id]
                read.shared_credential_id = sc.id
                read.shared_credential_name = sc.name
            secrets_read.append(read)
        assigned_ids = {pinned.skill.id for pinned in (skills or [])}
        req_ids = effective_required_ids(required_skill_map or {}, assigned_ids)
        skills_read = [
            AgentAssignedSkillRead.model_validate(
                {
                    **pinned.skill.model_dump(),
                    "version": pinned.version,
                    "required": pinned.skill.id in req_ids,
                }
            )
            for pinned in (skills or [])
        ]
        webhook_url = (
            f"{self.config.api_external_url}/api/v1/webhooks/teams/{agent.id}/messages"
            if agent.platform == AgentPlatform.TEAMS and self.config.api_external_url
            else None
        )
        resolved_model = agent.model or effective_default_model
        return AgentRead(
            id=agent.id,
            name=agent.name,
            status=agent.status,
            agent_type=agent.agent_type,
            organization_id=agent.organization_id,
            template_key=template_key,
            template_version=template_version,
            template_pin_type=template_pin_type,
            override_version=override_version,
            model=agent.model,
            model_source="override" if agent.model else "default",
            effective_model=resolved_model,
            running_model=agent.running_model,
            # A running pod that started on something else is the only case a surface
            # must not report the resolved value as current.
            pending_model=(resolved_model if agent.running_model and agent.running_model != resolved_model else ""),
            approval_mode=agent.approval_mode,
            slack_config=slack_config_read,
            teams_config=teams_config_read,
            telegram_config=telegram_config_read,
            discord_config=discord_config_read,
            # OpenClaw ignores approval_mode; report the effective AUTO default
            # instead of a stored value from before this became enforced, so
            # reads stay truthful even for agents persisted prior to this check.
            approval_mode=(agent.approval_mode if agent.agent_type == AgentType.HERMES else CommandApprovalMode.AUTO),
            secrets=secrets_read,
            skills=skills_read,
            allowed_actions=allowed_actions or [],
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _get_agent_read(self, agent: Agent, context: CurrentUserContext) -> AgentRead:
        secrets = self.repository.get_secrets_for_agent(agent.id)
        skills = [
            PinnedSkill(skill=s, version=row.pinned_version)
            for row, s in self.skill_repository.get_agent_skills_with_details(agent.id)
        ]
        template = self.template_repository.get_pinned_template(agent)
        required_map = self.template_repository.get_required_skill_map_for(template) if template else {}
        allowed_actions = self.authorization.allowed_actions(context, [agent])[agent.id]
        pin_type = (
            AgentTemplatePinType.OVERRIDE
            if isinstance(template, AgentTemplateOverrideVersion)
            else AgentTemplatePinType.SHARED
        )
        template_key = ""
        if isinstance(template, AgentTemplateOverrideVersion):
            template_key = template.source_template_key
        elif template is not None:
            template_key = template.template_key
        return self._build_agent_read(
            agent,
            secrets,
            skills,
            required_map,
            allowed_actions,
            effective_default_model=self.agent_settings_lookup.resolve_default_model(agent.organization_id),
            template_key=template_key,
            template_version=template.version if template else 0,
            template_pin_type=pin_type,
            override_version=template.version if isinstance(template, AgentTemplateOverrideVersion) else None,
        )

    def _release_unowned_litellm_key(
        self,
        agent: Agent,
        error: BaseException,
        *,
        plaintext_key: str | None = None,
    ) -> None:
        """Best-effort cleanup for a LiteLLM key generated during a create_agent
        call that ultimately failed. The key was never attached to a
        successfully created Agent, so it is unowned: delete it outright
        rather than blocking it, since there is no Agent history to preserve
        (contrast with delete_agent, which blocks the key of an Agent that did
        get created). If deletion fails, block the key as a safety fallback so
        it can no longer be used even though it wasn't removed from LiteLLM.
        ``plaintext_key`` is supplied when a failure happens after LiteLLM
        returned the key but before its encrypted form was prepared. Never
        raises and never logs the plaintext key.
        """
        if plaintext_key is None:
            if not agent.litellm_key_encrypted:
                return
            try:
                plaintext_key = decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
            except Exception as cleanup_exc:
                logger.warning(
                    "Failed to release unowned LiteLLM key for agent %s (%s: %s)",
                    agent.id,
                    type(cleanup_exc).__name__,
                    cleanup_exc,
                )
                return

        def safe_message(exc: BaseException) -> str:
            return str(exc).replace(plaintext_key, "[REDACTED]")

        delete_error: BaseException | None = None
        try:
            if self.litellm.delete_key(plaintext_key):
                return
            delete_error = LiteLLMError("delete_key returned False")
        except Exception as cleanup_exc:
            delete_error = cleanup_exc

        assert delete_error is not None
        try:
            self.litellm.block_key(plaintext_key)
        except Exception as block_exc:
            logger.warning(
                "Failed to release unowned LiteLLM key for agent %s after failed create (%s: %s); "
                "deletion failed (%s: %s), blocking also failed (%s: %s)",
                agent.id,
                type(error).__name__,
                safe_message(error),
                type(delete_error).__name__,
                safe_message(delete_error),
                type(block_exc).__name__,
                safe_message(block_exc),
            )
            return

        logger.warning(
            "Failed to delete unowned LiteLLM key for agent %s after failed create (%s: %s); "
            "deletion failed (%s: %s), blocked instead",
            agent.id,
            type(error).__name__,
            safe_message(error),
            type(delete_error).__name__,
            safe_message(delete_error),
        )

    def create_agent(self, data: AgentCreate, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        self.authorization.require_collection_scope(context, PermissionKey.AGENT_CREATE)
        self._ensure_model_allowed(data.model, org_id)
        self._ensure_approval_mode_supported(data.agent_type, data.approval_mode)

        # Pin to the requested version, or the lineage's latest if unspecified.
        if data.template_version is not None:
            template = self.template_repository.resolve_template(org_id, data.template_key, data.template_version)
            missing_detail = f"Template {data.template_key} v{data.template_version} not found"
        else:
            template = self.template_repository.resolve_latest_template(org_id, data.template_key)
            missing_detail = f"Template {data.template_key} not found"
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail)

        agent = Agent(
            organization_id=org_id,
            created_by_user_id=context.user.id,
            name=data.name,
            model=data.model or "",
            agent_type=data.agent_type,
            approval_mode=data.approval_mode,
        )
        self._set_pin(agent, template)

        # Validate that all template-required skills are present in the request:
        # every standalone-required skill, and at least one member of each
        # "at least one of" group (e.g. GitHub OR Bitbucket).
        required_map = self.template_repository.get_required_skill_map_for(template)
        standalone_ids, required_groups = split_requirements(required_map)
        selected_skill_ids = set(data.skill_ids)
        if standalone_ids - selected_skill_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Required template skills must be included in skill_ids",
            )
        for group_key in sorted(required_groups):
            members = required_groups[group_key]
            if not (members & selected_skill_ids):
                names = sorted(s.name for s in self.skill_repository.get_many_by_ids(list(members)))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"At least one of these template skills must be included in skill_ids: {', '.join(names)}",
                )

        # Preflight skill version pins before any persistence so an invalid pin
        # (nonexistent version, pin for a skill not in the request) is rejected
        # atomically rather than after the agent, configs, and secrets are saved.
        resolved_pins = self._resolve_skill_pins(data.skill_ids, data.skill_versions, set(), [], org_id)
        resolved_pin_by_skill_id = {pin.skill_id: pin for pin in resolved_pins}

        # Prepare Agent Secrets in memory without persisting them yet.
        # Integration credentials are separate from Communication Connections.
        prepared_secrets: list[AgentSecret] = []
        live_validation_contents: list[tuple[SecretProvider, Any]] = []
        for item in data.secrets:
            content = _enrich_atlassian_content(validate_content(item.provider, item.content))
            live_validation_contents.append((item.provider, content))
            prepared_secrets.append(
                AgentSecret(
                    agent_id=agent.id,
                    provider=item.provider,
                    secret_name=PROVIDER_DISPLAY_NAMES[item.provider],
                    content=encrypt_content(content, self.config.agent_token_encryption_key),
                )
            )

        # Shared credentials: look up each, verify org ownership, and prepare
        # link rows in memory. used_providers is recomputed every iteration so
        # a duplicate provider across two shared credentials in the same
        # request is rejected, not just a shared/manual collision.
        for attach in data.shared_credentials:
            shared_cred = self.shared_credential_repository.get_by_id_and_org(attach.shared_credential_id, org_id)
            if shared_cred is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Shared credential {attach.shared_credential_id} not found",
                )
            used_providers = {s.provider for s in prepared_secrets}
            if shared_cred.provider in used_providers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Provider {shared_cred.provider} already has a credential in this request",
                )
            shared_content = decrypt_content(
                shared_cred.provider,
                shared_cred.content,
                self.config.agent_token_encryption_key,
            )
            live_validation_contents.append((shared_cred.provider, shared_content))
            prepared_secrets.append(
                AgentSecret(
                    agent_id=agent.id,
                    provider=shared_cred.provider,
                    secret_name=shared_cred.name,
                    content=None,
                    shared_credential_id=shared_cred.id,
                )
            )

        # Resolve and validate skills now that all credentials are known.
        shared_providers = {s.provider for s in prepared_secrets if s.shared_credential_id}
        skills_to_assign = self._resolve_skills(
            data.skill_ids,
            data.secrets,
            org_id,
            extra_providers=shared_providers,
        )
        # Live validation runs only after all deterministic template, skill,
        # provider-coverage, and shared-credential checks have passed. The list is
        # built from this request, never from a client-side validation result.
        for provider, content in live_validation_contents:
            self._validate_live_integration(provider, content)

        # The creator always gets an explicit Owner AgentAccess row, even if they
        # currently have implicit full access as an Org Owner/Admin: it's what keeps
        # them able to manage the Agent if they're later demoted to Member (see
        # test_creator_keeps_assigned_agent_after_owner_is_demoted_to_member). This row
        # is hidden from the Share dialog and preserved across saves — see
        # AgentAccessService._assigned_members_for_agent / replace_access_settings.
        persisted_membership = context.user_organization_map.get(org_id)
        creator_membership_id = (
            persisted_membership.id
            if persisted_membership is not None and persisted_membership.user_id == context.user.id
            else None
        )
        secret_actor = resolve_actor_identity(context, org_id)
        secret_actor_display = context.user.full_name or context.user.email

        # All deterministic, client-visible validation and in-memory preparation
        # is complete. Allocate the LiteLLM key immediately before Agent
        # persistence so a rejected create never allocates one (AF-272); any
        # failure before the atomic create transaction commits releases the
        # unowned key.
        prepared_skills = [
            AgentSkill(
                agent_id=agent.id,
                skill_id=s.id,
                pinned_version=resolved_pin_by_skill_id[s.id].version,
            )
            for s in skills_to_assign
        ]
        allocated_litellm_key: str | None = None
        try:
            if self.config.litellm_base_url and self.config.litellm_secret_name:
                try:
                    allocated_litellm_key = self.litellm.generate_key(
                        str(agent.id), agent.name, str(agent.organization_id)
                    )
                except LiteLLMError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="LiteLLM key generation failed; cannot create agent.",
                    ) from exc
                agent.litellm_key_encrypted = encrypt_token(
                    allocated_litellm_key,
                    self.config.agent_token_encryption_key,
                )

            created = self.repository.create_with_creator_access(
                agent,
                creator_membership_id,
                actor=secret_actor,
                secrets=prepared_secrets,
                skills=prepared_skills,
                actor_display=secret_actor_display,
            )
            created_delivery_ids = created.delivery_ids
        except Exception as exc:
            if allocated_litellm_key is not None:
                self._release_unowned_litellm_key(agent, exc, plaintext_key=allocated_litellm_key)
            raise

        skills_read_versions = [
            PinnedSkill(skill=s, version=resolved_pin_by_skill_id[s.id].version) for s in skills_to_assign
        ]

        self.event_delivery_dispatcher.enqueue_immediate(created_delivery_ids)

        allowed_actions = self.authorization.allowed_actions(context, [agent])[agent.id]
        return self._build_agent_read(
            agent,
            prepared_secrets,
            skills_read_versions,
            required_map,
            allowed_actions,
            template_key=template.template_key,
            template_version=template.version,
            effective_default_model=self.agent_settings_lookup.resolve_default_model(org_id),
        )

    def get_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        agent = self.authorization.require_visible(context, agent_id)
        return self._get_agent_read(agent, context)

    def get_agent_template(self, agent_id: UUID, version: int, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_visible(context, agent_id)
        pinned = self.template_repository.get_pinned_template(agent)
        if pinned is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} has no pinned template",
            )
        if isinstance(pinned, AgentTemplateOverrideVersion):
            if pinned.version != version:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template version {version} not found for agent {agent_id}",
                )
            return self.template_repository.to_override_read(
                pinned,
                org_id,
                self.template_repository.get_required_skills_for(pinned),
            )
        template = self.template_repository.resolve_template(org_id, pinned.template_key, version)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template version {version} not found for agent {agent_id}",
            )
        return self.template_repository.to_read(template, self.template_repository.get_required_skills_for(template))

    def _get_available_source_update(
        self,
        agent: Agent,
        organization_id: UUID,
        active: AgentTemplateOverrideVersion,
    ) -> AgentConfigurationVersionRead | None:
        """Resolve a newer row in the Override's direct source lineage.

        Source IDs are checked before looking for a newer version. If the
        original source row was removed, the Override remains self-contained but
        there is no update candidate to display.
        """
        baseline = active
        if baseline.source_type == AgentTemplateOverrideSourceType.PLATFORM:
            if baseline.source_platform_template_id is None:
                return None
            source = self.template_repository.get_platform_template_by_id(baseline.source_platform_template_id)
            latest = self.template_repository.get_latest_platform_template(baseline.source_template_key)
        else:
            if baseline.source_agent_template_id is None:
                return None
            source = self.template_repository.get_org_template_by_id(
                organization_id,
                baseline.source_agent_template_id,
            )
            latest = self.template_repository.get_latest_org_template(
                organization_id,
                baseline.source_template_key,
            )
        if (
            source is None
            or source.template_key != baseline.source_template_key
            or source.version != baseline.source_template_version
            or latest is None
            or latest.version <= baseline.source_template_version
        ):
            return None
        return self._shared_configuration_read(
            latest,
            agent,
            self.template_repository.get_required_skills_for(latest),
        )

    def get_agent_configuration(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
    ) -> AgentConfigurationRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_visible(context, agent_id)
        active = self.template_repository.get_pinned_template(agent)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} has no pinned template",
            )

        draft = self.override_repository.get_draft(agent.id, org_id)
        versions = self.override_repository.get_versions(agent.id, org_id)
        override_version_ids = [version.id for version in versions]
        if isinstance(active, AgentTemplateOverrideVersion) and active.id not in override_version_ids:
            override_version_ids.append(active.id)
        skills_by_version = self.override_repository.get_skills_for_versions(override_version_ids)

        author_ids = {version.created_by_user_id for version in versions if version.created_by_user_id is not None}
        if isinstance(active, AgentTemplateOverrideVersion) and active.created_by_user_id is not None:
            author_ids.add(active.created_by_user_id)
        if draft is not None and draft.created_by_user_id is not None:
            author_ids.add(draft.created_by_user_id)
        authors_by_id = self.override_repository.get_authors(author_ids)

        if isinstance(active, AgentTemplateOverrideVersion):
            active_read = self._active_override_read(
                active,
                skills=skills_by_version.get(active.id, []),
                author=authors_by_id.get(active.created_by_user_id) if active.created_by_user_id is not None else None,
            )
            shared_key = active.source_template_key
        else:
            active_read = self._shared_configuration_read(
                active,
                agent,
                self.template_repository.get_required_skills_for(active),
            )
            shared_key = active.template_key

        draft_read = (
            self._override_draft_read(
                draft,
                skills=self.override_repository.get_skills_for_draft(draft.id),
                author=authors_by_id.get(draft.created_by_user_id) if draft.created_by_user_id is not None else None,
            )
            if draft is not None
            else None
        )
        source_update = (
            self._get_available_source_update(agent, org_id, active)
            if isinstance(active, AgentTemplateOverrideVersion)
            else None
        )
        version_reads = [
            self._override_version_read(
                version,
                skills=skills_by_version.get(version.id, []),
                author=authors_by_id.get(version.created_by_user_id)
                if version.created_by_user_id is not None
                else None,
            )
            for version in versions
        ]
        shared_reads = [
            self._shared_configuration_read(
                shared,
                agent,
                self.template_repository.get_required_skills_for(shared),
            )
            for shared in self.template_repository.get_shared_versions(org_id, shared_key)
        ]
        return AgentConfigurationRead(
            agent_id=agent.id,
            active=active_read,
            draft=draft_read,
            source_update=source_update,
            shared_versions=shared_reads,
            override_versions=version_reads,
        )

    def start_agent_override_draft(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
    ) -> AgentTemplateOverrideDraftRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        existing = self.override_repository.get_draft(agent.id, org_id)
        if existing is not None:
            return self._override_draft_read(
                existing,
                skills=self.override_repository.get_skills_for_draft(existing.id),
                author=self.override_repository.get_author(existing.created_by_user_id),
            )

        active = self.template_repository.get_pinned_template(agent)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} has no pinned template",
            )
        if isinstance(active, AgentTemplateOverrideVersion):
            required_map = self.override_repository.get_version_skill_map(active.id)
            snapshot = AgentOverrideSnapshot.from_override_version(active, required_map)
            expected_pin_type = "override"
            expected_pin_id = active.id
        else:
            required_map = self.template_repository.get_required_skill_map_for(active)
            snapshot = AgentOverrideSnapshot.from_template(active, required_map)
            expected_pin_type = "platform" if isinstance(active, PlatformTemplate) else "organization"
            expected_pin_id = active.id

        draft = AgentTemplateOverrideDraft(
            organization_id=org_id,
            agent_id=agent.id,
            created_by_user_id=context.user.id,
            **snapshot.model_values(),
        )
        try:
            saved = self.override_repository.create_draft(
                draft,
                snapshot,
                expected_pin_type=expected_pin_type,
                expected_pin_id=expected_pin_id,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
            )
        except AgentOverrideConcurrencyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return self._override_draft_read(
            saved,
            skills=self.override_repository.get_skills_for_draft(saved.id),
            author=self.override_repository.get_author(saved.created_by_user_id),
        )

    def update_agent_override_draft(
        self,
        agent_id: UUID,
        data: AgentTemplateOverrideDraftUpdate,
        context: CurrentUserContext,
    ) -> AgentTemplateOverrideDraftRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        updated = data.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
        skill_map = None
        if data.required_skill_ids is not None or data.required_skill_groups is not None:
            existing_map = self.override_repository.get_draft_skill_map_for_agent(agent.id, org_id)
            if data.required_skill_ids is None:
                standalone_ids = {skill_id for skill_id, group_key in existing_map.items() if group_key is None}
            else:
                standalone_ids = set(data.required_skill_ids)
            if data.required_skill_groups is None:
                groups_map = {
                    skill_id: group_key for skill_id, group_key in existing_map.items() if group_key is not None
                }
            else:
                groups_map = {
                    skill_id: group.group_key for group in data.required_skill_groups for skill_id in group.skill_ids
                }
            skill_map = {skill_id: None for skill_id in standalone_ids} | groups_map
            self._validate_override_requirements(agent, skill_map, org_id)
        try:
            saved = self.override_repository.update_draft(
                agent.id,
                org_id,
                updated,
                skill_map,
                expected_updated_at=data.expected_updated_at,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
            )
        except AgentOverrideConcurrencyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return self._override_draft_read(
            saved,
            skills=self.override_repository.get_skills_for_draft(saved.id),
            author=self.override_repository.get_author(saved.created_by_user_id),
        )

    def publish_agent_override(
        self,
        agent_id: UUID,
        data: AgentTemplateOverridePublish,
        context: CurrentUserContext,
    ) -> AgentTemplateOverrideVersionRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        draft = self.override_repository.get_draft(agent.id, org_id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No Override Draft for agent {agent_id}")
        self._validate_override_requirements(
            agent,
            self.override_repository.get_draft_skill_map(draft.id),
            org_id,
        )
        try:
            published = self.override_repository.publish_draft(
                agent.id,
                org_id,
                actor_user_id=context.user.id,
                expected_updated_at=data.expected_updated_at,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
            )
        except AgentOverrideConcurrencyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return self._override_version_read(
            published,
            skills=self.override_repository.get_skills_for_version(published.id),
            author=self.override_repository.get_author(published.created_by_user_id),
        )

    def select_agent_template(
        self,
        agent_id: UUID,
        data: AgentTemplateSelection,
        context: CurrentUserContext,
    ) -> AgentRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} must be stopped before selecting a Template Version",
            )

        selected_id: UUID
        selected_template_key: str | None
        selected_version: int | None
        required_map: dict[UUID, str | None]
        if data.selection_type == "platform":
            assert data.template_key is not None and data.template_version is not None
            selected = self.template_repository.get_platform_template_by_key_version(
                data.template_key,
                data.template_version,
            )
            if selected is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform Template Version not found")
            selected_id = selected.id
            selected_template_key = selected.template_key
            selected_version = selected.version
            required_map = self.template_repository.get_required_skill_map_for(selected)
        elif data.selection_type == "organization":
            assert data.template_key is not None and data.template_version is not None
            selected = self.template_repository.get_org_template_by_key_version(
                org_id,
                data.template_key,
                data.template_version,
            )
            if selected is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization Template Version not found",
                )
            selected_id = selected.id
            selected_template_key = selected.template_key
            selected_version = selected.version
            required_map = self.template_repository.get_required_skill_map_for(selected)
        else:
            assert data.override_version is not None
            selected_override = self.override_repository.get_version(
                agent.id,
                org_id,
                data.override_version,
            )
            if selected_override is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent Template Override Version not found",
                )
            selected_id = selected_override.id
            selected_template_key = None
            selected_version = selected_override.version
            required_map = self.override_repository.get_version_skill_map(selected_override.id)
        self._validate_override_requirements(agent, required_map, org_id)
        try:
            selected_agent = self.override_repository.select_pin(
                agent.id,
                org_id,
                selection_type=data.selection_type,
                selected_id=selected_id,
                expected_agent_updated_at=data.expected_agent_updated_at,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
                template_key=selected_template_key,
                selected_version=selected_version,
            )
        except AgentOverrideConcurrencyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return self._get_agent_read(selected_agent, context)

    def _validate_override_requirements(
        self,
        agent: Agent,
        required_map: dict[UUID, str | None],
        org_id: UUID,
    ) -> None:
        if not required_map:
            return
        accessible = {skill.id: skill for skill in self.skill_repository.find_accessible_for_org(org_id)}
        missing_ids = set(required_map) - accessible.keys()
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Override requires a Skill that is no longer available to this Organization",
            )
        assigned_ids = {skill.id for _, skill in self.skill_repository.get_agent_skills_with_details(agent.id)}
        standalone_ids, groups = split_requirements(required_map)
        if standalone_ids - assigned_ids:
            missing = ", ".join(sorted(accessible[skill_id].name for skill_id in standalone_ids - assigned_ids))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Required template skills must be assigned to the Agent: {missing}",
            )
        for group_key, member_ids in sorted(groups.items()):
            if not member_ids & assigned_ids:
                names = ", ".join(sorted(accessible[skill_id].name for skill_id in member_ids))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"At least one of these template skills must be assigned to the Agent: {names}",
                )
        providers = {secret.provider for secret in self.repository.get_secrets_for_agent(agent.id)}
        for skill_id in required_map:
            missing_providers = set(accessible[skill_id].required_providers) - providers
            if missing_providers:
                names = ", ".join(sorted(provider.value for provider in missing_providers))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Required Skill '{accessible[skill_id].name}' needs configured providers: {names}",
                )

    def _override_draft_read(
        self,
        draft: AgentTemplateOverrideDraft,
        *,
        skills: list[tuple[Skill, str | None]],
        author: User | None,
    ) -> AgentTemplateOverrideDraftRead:
        return AgentTemplateOverrideDraftRead(
            **self._override_snapshot_values(
                draft,
                agent_id=draft.agent_id,
                version=None,
                skills=skills,
                author=author,
            ),
        )

    def _override_version_read(
        self,
        version: AgentTemplateOverrideVersion,
        *,
        skills: list[tuple[Skill, str | None]],
        author: User | None,
    ) -> AgentTemplateOverrideVersionRead:
        values = self._override_snapshot_values(
            version,
            agent_id=version.agent_id,
            version=version.version,
            skills=skills,
            author=author,
        )
        return AgentTemplateOverrideVersionRead(**values)

    def _active_override_read(
        self,
        version: AgentTemplateOverrideVersion,
        *,
        skills: list[tuple[Skill, str | None]],
        author: User | None,
    ) -> AgentConfigurationVersionRead:
        return AgentConfigurationVersionRead(
            **self._override_snapshot_values(
                version,
                agent_id=version.agent_id,
                version=version.version,
                skills=skills,
                author=author,
            ),
            state="active",
            pin_type=AgentTemplatePinType.OVERRIDE,
        )

    @staticmethod
    def _required_skill_read(
        skill: Skill,
        group_key: str | None,
    ) -> AgentTemplateOverrideRequiredSkillRead:
        source = skill.source.value if hasattr(skill.source, "value") else skill.source
        required_providers = [
            provider.value if hasattr(provider, "value") else provider for provider in skill.required_providers
        ]
        return AgentTemplateOverrideRequiredSkillRead(
            id=skill.id,
            organization_id=skill.organization_id,
            name=skill.name,
            source=source,
            required_providers=required_providers,
            tools_pointer=skill.tools_pointer,
            group_key=group_key,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    def _override_snapshot_values(
        self,
        snapshot: AgentTemplateOverrideDraft | AgentTemplateOverrideVersion,
        *,
        agent_id: UUID,
        version: int | None,
        skills: list[tuple[Skill, str | None]],
        author: User | None,
    ) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "agent_id": agent_id,
            "version": version,
            "template_key": snapshot.source_template_key,
            "template_name": snapshot.template_name,
            "description": snapshot.description,
            "soul_md": snapshot.soul_md,
            "identity_md": snapshot.identity_md,
            "user_md": snapshot.user_md,
            "tools_md": snapshot.tools_md,
            "agents_md": snapshot.agents_md,
            "boot_md": snapshot.boot_md,
            "bootstrap_md": snapshot.bootstrap_md,
            "heartbeat_md": snapshot.heartbeat_md,
            "source_type": snapshot.source_type,
            "source_template_key": snapshot.source_template_key,
            "source_template_version": snapshot.source_template_version,
            "source_platform_template_id": snapshot.source_platform_template_id,
            "source_agent_template_id": snapshot.source_agent_template_id,
            "created_by_user_id": snapshot.created_by_user_id,
            "author": (
                AgentOverrideAuthorRead(
                    user_id=author.id,
                    email=str(author.email),
                    full_name=author.full_name,
                )
                if author is not None
                else None
            ),
            "required_skills": [self._required_skill_read(skill, group_key) for skill, group_key in skills],
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
        }

    def _shared_configuration_read(
        self,
        template: AgentTemplate | PlatformTemplate,
        agent: Agent,
        skills: list[tuple[Skill, str | None]],
    ) -> AgentConfigurationVersionRead:
        source_type = (
            AgentTemplateOverrideSourceType.PLATFORM
            if isinstance(template, PlatformTemplate)
            else AgentTemplateOverrideSourceType.ORGANIZATION
        )
        return AgentConfigurationVersionRead(
            id=template.id,
            agent_id=agent.id,
            version=template.version,
            template_key=template.template_key,
            template_name=template.template_name,
            description=template.description,
            soul_md=template.soul_md,
            identity_md=template.identity_md,
            user_md=template.user_md,
            tools_md=template.tools_md,
            agents_md=template.agents_md,
            boot_md=template.boot_md,
            bootstrap_md=template.bootstrap_md,
            heartbeat_md=template.heartbeat_md,
            source_type=source_type,
            source_template_key=template.template_key,
            source_template_version=template.version,
            source_platform_template_id=template.id if isinstance(template, PlatformTemplate) else None,
            source_agent_template_id=template.id if isinstance(template, AgentTemplate) else None,
            created_by_user_id=None,
            author=None,
            required_skills=[self._required_skill_read(skill, group_key) for skill, group_key in skills],
            created_at=template.created_at,
            updated_at=template.updated_at,
            state="active" if self._is_active_shared_pin(agent, template.id) else "published",
            pin_type=AgentTemplatePinType.SHARED,
            template_source="pre-defined" if isinstance(template, PlatformTemplate) else "custom",
        )

    @staticmethod
    def _is_active_shared_pin(agent: Agent, template_id: UUID) -> bool:
        return template_id in {agent.platform_template_id, agent.agent_template_id}

    def list_agents(
        self,
        agent_filter: AgentFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[AgentRead]:
        read_scope = self.authorization.require_collection_scope(context, PermissionKey.AGENT_READ)
        agents, total = self.repository.find_all_active(read_scope, agent_filter, pagination)
        allowed_actions = self.authorization.allowed_actions(context, agents)

        agent_ids = [a.id for a in agents]
        secrets_by_agent = self.repository.get_secrets_for_agents(agent_ids)
        skills_by_agent = self.skill_repository.get_skills_for_agents_with_versions(agent_ids)

        req_maps_by_agent = self.template_repository.get_required_skill_map_for_agents(agents)
        pin_info = self.template_repository.get_pinned_template_info_for_agents(agents)
        # Resolved once for the page. Every Agent in it belongs to the same
        # Organization, so resolving per row would be one query per row.
        effective_default_model = self.agent_settings_lookup.resolve_default_model(read_scope.organization_id)

        items = [
            self._build_agent_read(
                agent,
                secrets_by_agent.get(agent.id, []),
                skills_by_agent.get(agent.id, []),
                req_maps_by_agent.get(agent.id, {}),
                allowed_actions.get(agent.id, []),
                template_key=pin_info.get(agent.id, ("", 0, "shared", None))[0],
                template_version=pin_info.get(agent.id, ("", 0, "shared", None))[1],
                template_pin_type=(
                    AgentTemplatePinType.OVERRIDE
                    if pin_info.get(agent.id, ("", 0, "shared", None))[2] == "override"
                    else AgentTemplatePinType.SHARED
                ),
                override_version=pin_info.get(agent.id, ("", 0, "shared", None))[3],
                effective_default_model=effective_default_model,
            )
            for agent in agents
        ]

        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=items,
        )

    def update_agent(self, agent_id: UUID, data: AgentUpdate, context: CurrentUserContext) -> AgentRead:
        org_id = self._org_id(context)
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        updated = data.model_dump(exclude_unset=True)
        if _CREDENTIAL_FIELDS & updated.keys():
            self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)

        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} must be stopped before updating",
            )

        if "approval_mode" in updated:
            self._ensure_approval_mode_supported(agent.agent_type, updated["approval_mode"])

        # Validate every requested skill pin before mutating the Agent, its
        # template pin, or any attached credential.
        current_skill_rows = self.repository.get_skills_for_agent(agent.id)
        current_skill_ids = {row.skill_id for row in current_skill_rows}
        resolved_skill_pins = self._resolve_skill_pins(
            data.skill_ids,
            data.skill_versions,
            current_skill_ids,
            data.removed_skill_ids,
            org_id,
        )

        # Re-pin the agent to a different template (key, version). The model
        # validator guarantees both keys appear together.
        effective_template = None
        if "template_key" in updated:
            effective_template = self.template_repository.resolve_template(
                org_id, updated["template_key"], updated["template_version"]
            )
            if effective_template is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(f"Template {updated['template_key']} v{updated['template_version']} not found"),
                )
            self._set_pin(agent, effective_template)

        if "name" in updated:
            agent.name = updated["name"]

        if "model" in updated:
            self._ensure_model_allowed(updated["model"], org_id)
            # An explicit null (or empty string) clears the override and returns the
            # Agent to its Organization's default. The column is non-nullable, so the
            # sentinel is "", never None.
            agent.model = updated["model"] or ""

        if "approval_mode" in updated:
            agent.approval_mode = updated["approval_mode"]

        # Validate skill changes against the effective template's required skills
        if effective_template is None:
            effective_template = self.template_repository.get_pinned_template(agent)
        required_map = (
            self.template_repository.get_required_skill_map_for(effective_template) if effective_template else {}
        )
        if required_map:
            standalone_ids, required_groups = split_requirements(required_map)
            existing_skill_ids = current_skill_ids
            effective_skill_ids = (existing_skill_ids | set(data.skill_ids)) - set(data.removed_skill_ids)
            # Block removal of required skills.
            if data.removed_skill_ids:
                blocked = standalone_ids & set(data.removed_skill_ids)
                if blocked:
                    blocked_skills = self.skill_repository.get_many_by_ids(list(blocked))
                    names = ", ".join(s.name for s in blocked_skills)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot remove skills required by the template: {names}",
                    )
                for group_key in sorted(required_groups):
                    members = required_groups[group_key]
                    # Only block if the group had an assigned member before this
                    # update; this grandfathers agents whose pinned template
                    # gained the group after they were created (e.g. via an
                    # in-place predefined-template reseed), and permits swapping
                    # one member for another in the same request.
                    if (members & existing_skill_ids) and not (members & effective_skill_ids):
                        names = sorted(s.name for s in self.skill_repository.get_many_by_ids(list(members)))
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=("At least one of these template-required skills must remain: " + ", ".join(names)),
                        )
            # When re-pinning, validate that required skills will be present.
            if "template_key" in updated:
                if standalone_ids - effective_skill_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Required template skills must be included in skill_ids",
                    )
                for group_key in sorted(required_groups):
                    members = required_groups[group_key]
                    if not (members & effective_skill_ids):
                        names = sorted(s.name for s in self.skill_repository.get_many_by_ids(list(members)))
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                "At least one of these template skills must be included in skill_ids: "
                                + ", ".join(names)
                            ),
                        )

        # Validate skills accessibility and secret coverage
        if data.skill_ids or data.removed_secret_providers:
            self._validate_skill_update(agent, data, org_id)

        secret_actor = resolve_actor_identity(context, org_id)
        secret_actor_display = context.user.full_name or context.user.email
        secret_delivery_ids: list[UUID] = []

        # Integration secrets: platform-independent. Remove first, then upsert
        # (the AgentUpdate validator already forbids a provider in both lists).
        # Validate and encrypt all upserts before touching the DB so that a
        # validation failure never leaves already-deleted secrets permanently gone.
        if "removed_secret_providers" in updated or "secrets" in updated:
            key = self.config.agent_token_encryption_key
            upserts: list[tuple[AgentSecretCreate, str]] = [
                (
                    item,
                    encrypt_content(
                        _enrich_atlassian_content(validate_content(item.provider, item.content)),
                        key,
                    ),
                )
                for item in data.secrets or []
            ]
            for provider in updated.get("removed_secret_providers") or []:
                secret_delivery_ids += self.repository.delete_secret_with_event(
                    agent.id,
                    provider,
                    organization_id=org_id,
                    agent_name=agent.name,
                    actor=secret_actor,
                    actor_display=secret_actor_display,
                )
            for item, encrypted in upserts:
                existing = self.repository.get_secret(agent.id, item.provider)
                if existing:
                    existing.content = encrypted
                    existing.shared_credential_id = None
                    existing.secret_name = PROVIDER_DISPLAY_NAMES[item.provider]
                    secret_delivery_ids += self.repository.save_secret_with_event(
                        existing,
                        event_name=AGENT_SECRET_UPDATED,
                        organization_id=org_id,
                        agent_name=agent.name,
                        actor=secret_actor,
                        actor_display=secret_actor_display,
                    )
                else:
                    secret = AgentSecret(
                        agent_id=agent.id,
                        provider=item.provider,
                        secret_name=PROVIDER_DISPLAY_NAMES[item.provider],
                        content=encrypted,
                    )
                    secret_delivery_ids += self.repository.save_secret_with_event(
                        secret,
                        event_name=AGENT_SECRET_ADDED,
                        organization_id=org_id,
                        agent_name=agent.name,
                        actor=secret_actor,
                        actor_display=secret_actor_display,
                    )

        # Shared credential attachments
        if "shared_credentials" in updated:
            current_secrets = self.repository.get_secrets_for_agent(agent.id)
            manual_providers = {s.provider for s in current_secrets if not s.shared_credential_id}
            shared_providers_seen: set[str] = set()
            for attach in data.shared_credentials or []:
                shared_cred = self.shared_credential_repository.get_by_id_and_org(attach.shared_credential_id, org_id)
                if shared_cred is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Shared credential {attach.shared_credential_id} not found",
                    )
                if shared_cred.provider in manual_providers:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Provider {shared_cred.provider} already has a manual credential",
                    )
                if shared_cred.provider in shared_providers_seen:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Duplicate shared credential provider: {shared_cred.provider}",
                    )
                shared_providers_seen.add(shared_cred.provider)
                existing = self.repository.get_secret(agent.id, shared_cred.provider)
                if existing:
                    existing.content = None
                    existing.shared_credential_id = shared_cred.id
                    existing.secret_name = shared_cred.name
                    secret_delivery_ids += self.repository.save_secret_with_event(
                        existing,
                        event_name=AGENT_SECRET_UPDATED,
                        organization_id=org_id,
                        agent_name=agent.name,
                        actor=secret_actor,
                        actor_display=secret_actor_display,
                    )
                else:
                    secret = AgentSecret(
                        agent_id=agent.id,
                        provider=shared_cred.provider,
                        secret_name=shared_cred.name,
                        content=None,
                        shared_credential_id=shared_cred.id,
                    )
                    secret_delivery_ids += self.repository.save_secret_with_event(
                        secret,
                        event_name=AGENT_SECRET_ADDED,
                        organization_id=org_id,
                        agent_name=agent.name,
                        actor=secret_actor,
                        actor_display=secret_actor_display,
                    )

        # Apply skill changes (pins were preflighted before persistence above)
        for skill_id in data.removed_skill_ids:
            self.repository.remove_skill(agent.id, skill_id)
        for pin in resolved_skill_pins:
            if pin.skill_id in current_skill_ids:
                self.repository.re_pin_skill(agent.id, pin.skill_id, pin.version)
            else:
                self.repository.add_skill(agent.id, pin.skill_id, pinned_version=pin.version)

        update_result = self.repository.update_scalar_fields_with_event(
            agent, actor=secret_actor, actor_display=secret_actor_display
        )
        self.event_delivery_dispatcher.enqueue_immediate(update_result.delivery_ids + secret_delivery_ids)
        return self._get_agent_read(update_result.agent, context)

    def start_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        started = self._start_agent_unchecked(agent, resolve_actor_identity(context, agent.organization_id))
        return self._get_agent_read(started, context)

    def _start_agent_unchecked(self, agent: Agent, actor: ActorIdentity) -> Agent:
        """Start a known Agent after its caller has established authority."""
        agent_id = agent.id
        org_id = agent.organization_id
        # Stamped as Service labels for monitoring; resolved here (not in the
        # route) so every start path labels agents consistently.
        org_name = self.organization_lookup.get_name(org_id)
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent_id} is already running",
            )

        previous_status = agent.status.value
        template = self.template_repository.get_pinned_template(agent)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} has no pinned template",
            )
        # Placeholders are kept raw in storage and rendered at seed time.
        rendered = render_template(template, agent.name)
        ns = self.config.k8s_namespace

        name = f"agent-{agent.id}"
        litellm_key = (
            decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
            if agent.litellm_key_encrypted
            else ""
        )
        effective_model = agent.model or self.agent_settings_lookup.resolve_default_model(org_id)
        llm_proxy_url = "http://localhost:8090"

        # Re-check the allowlist at start time, not just create/update: the org's
        # allowlist can change after the agent was created, and a model that was
        # valid then may no longer be permitted now.
        #
        # Only an explicit override is re-checked. An Agent that inherits is running
        # the Organization's policy rather than a user's choice: when the Organization
        # set its own default, the allowlist invariant already keeps that model inside
        # the list, and when it did not, the model is the platform default the
        # Organization has no way to police. Failing the start in either case would
        # punish the Agent for a decision nobody made about it.
        if agent.model:
            allowed_models = self.organization_lookup.get_allowed_models(org_id)
            if allowed_models is None or not is_model_allowed(agent.model, allowed_models):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Model '{agent.model}' is no longer in the organization's allowed model list",
                )

        runtime_api_key = secrets.token_urlsafe(32)
        service = build_service(agent.id, org_id, ns, org_name=org_name, agent_name=agent.name)
        if agent.agent_type == AgentType.HERMES:
            overlay = None
            hermes_cfg = build_hermes_gateway_config(
                effective_model,
                llm_proxy_url,
                approval_mode=str(agent.approval_mode),
            )
            secret = build_secret_hermes_runtime(
                agent.id,
                org_id,
                ns,
                agent.name,
                runtime_api_key=runtime_api_key,
                litellm_api_key=litellm_key,
                litellm_base_url=llm_proxy_url,
            )
            deployment = build_hermes_deployment(
                agent.id,
                org_id,
                ns,
                self.config.hermes_image,
                self.config.agent_image_pull_secret,
            )
        else:
            overlay = build_openclaw_gateway_config(effective_model, llm_proxy_url)
            hermes_cfg = None
            secret = build_secret_runtime(
                agent.id,
                org_id,
                ns,
                runtime_api_key=runtime_api_key,
                litellm_api_key=litellm_key,
                litellm_base_url=llm_proxy_url,
            )
            deployment = build_deployment(
                agent.id,
                org_id,
                ns,
                self.config.openclaw_image,
                self.config.agent_image_pull_secret,
            )

        # aai-cli integration secrets — all agent types.
        agent_secrets = self.repository.get_secrets_for_agent(agent.id)
        shared_ids = [s.shared_credential_id for s in agent_secrets if s.shared_credential_id is not None]
        shared_by_id = {}
        if shared_ids:
            shared_creds = self.shared_credential_repository.get_by_ids_and_org(shared_ids, org_id)
            shared_by_id = {c.id: c for c in shared_creds}
        key = self.config.agent_token_encryption_key
        decrypted = {}
        for s in agent_secrets:
            provider = SecretProvider(s.provider)
            if s.shared_credential_id and s.shared_credential_id in shared_by_id:
                ciphertext = shared_by_id[s.shared_credential_id].content
            else:
                ciphertext = s.content
            assert ciphertext is not None
            decrypted[provider] = decrypt_content(provider, ciphertext, key)
        self._backfill_google_client_credentials(decrypted)
        # Only google_workspace is materialized. The retired per-service Google providers
        # and their rows were deleted by migration; affected agents must reconnect through
        # Google Workspace.
        gws_content = decrypted.get(SecretProvider.GOOGLE_WORKSPACE)
        if isinstance(gws_content, GoogleWorkspaceContent) and (
            not gws_content.client_id or not gws_content.client_secret
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{PROVIDER_DISPLAY_NAMES[SecretProvider.GOOGLE_WORKSPACE]} is missing a client id/secret "
                    "and Google OAuth is not configured on this server. Reconnect via "
                    "Authenticate with Google, or configure google_cloud_client_id/secret."
                ),
            )
        store = {p: c for p, c in decrypted.items() if p.value in provider_secrets_map}
        aai_home = "/opt/data" if agent.agent_type == AgentType.HERMES else "/home/node"
        # Gated on providers that actually get an aai-cli profile: an agent whose only
        # integrations are profile-less (google_workspace, firecrawl) would otherwise get
        # a config.toml holding nothing but the store header.
        has_aai_profiles = bool(decrypted.keys() & set(PROFILE_SLUGS))
        aai_config_toml = build_config_toml(decrypted, home_dir=aai_home) if has_aai_profiles else None
        aai_setup_sh = build_setup_sh(list(store), home_dir=aai_home) if has_aai_profiles else None
        if store:
            secret.string_data.update(build_env(store))

        # gog (Google Workspace) — its own CLI with its own on-disk state, rebuilt from
        # this secret on every boot. GOG_HOME is deliberately the container filesystem,
        # not the PVC that aai_home points at for Hermes.
        gog_setup_sh = None
        if isinstance(gws_content, GoogleWorkspaceContent):
            gog_home_dir = "/home/hermes" if agent.agent_type == AgentType.HERMES else "/home/node"
            secret.string_data.update(
                build_gog_env(gws_content, gog_home_dir, secrets.token_urlsafe(32)),
            )
            gog_setup_sh = build_gog_setup_sh()

        fc_content = decrypted.get(SecretProvider.FIRECRAWL)
        fc_api_key = (
            fc_content.api_key if isinstance(fc_content, FirecrawlContent) else self.config.agent_firecrawl_api_key
        )
        fc_base_url = (
            fc_content.base_url
            if isinstance(fc_content, FirecrawlContent) and fc_content.base_url
            else self.config.agent_firecrawl_base_url
        )
        if fc_api_key and fc_base_url:
            secret.string_data["FIRECRAWL_API_KEY"] = fc_api_key
            if hermes_cfg is not None:
                hermes_cfg["web"] = {"backend": "firecrawl"}
                hermes_cfg["browser"] = {"cloud_provider": "firecrawl"}
                secret.string_data["FIRECRAWL_API_URL"] = fc_base_url
                secret.string_data["FIRECRAWL_BROWSER_TTL"] = "600"
            if overlay is not None:
                overlay["plugins"]["allow"].append("firecrawl")
                overlay["plugins"]["entries"]["firecrawl"] = {
                    "enabled": True,
                    "config": {
                        "webSearch": {
                            "apiKey": "${FIRECRAWL_API_KEY}",
                            "baseUrl": fc_base_url,
                        },
                        "webFetch": {
                            "apiKey": "${FIRECRAWL_API_KEY}",
                            "baseUrl": fc_base_url,
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

        ingest_key = secrets.token_urlsafe(32)
        communication_key = secrets.token_urlsafe(32)
        secret.string_data.update(
            {
                "AGENT_ID": str(agent.id),
                "INGEST_URL": self.config.ingest_base_url,
                "INGEST_API_KEY": ingest_key,
                "COMMUNICATIONS_URL": self.config.communications_base_url,
                "COMMUNICATIONS_API_KEY": communication_key,
                "COMMUNICATIONS_PROTOCOL_VERSION": "1",
                "LITELLM_PROXY_TARGET": self.config.agent_litellm_base_url,
            }
        )

        agent_skills = self.skill_repository.get_agent_skills_with_details(agent.id)
        assigned_skills = [s for _, s in agent_skills]
        # Implicitly mount the aai-cli skill for any configured provider.
        mounted_skills = assigned_skills + self._auto_attached_aai_cli_skills(
            set(decrypted.keys()),
            {s.id for s in assigned_skills},
        )
        skills_json = None
        if mounted_skills:
            pinned_by_id = {s.id: SkillVersionPin(skill_id=s.id, version=row.pinned_version) for row, s in agent_skills}
            # Explicitly assigned skills mount their pinned version; implicit
            # aai-cli mounts resolve to the built-in's latest.
            pins_to_mount: list[SkillVersionPin] = []
            for skill in mounted_skills:
                pin = pinned_by_id.get(skill.id)
                if pin is None:
                    latest = self.skill_repository.get_latest_version(skill.id)
                    pin = SkillVersionPin(skill_id=skill.id, version=latest.version if latest else 1)
                pins_to_mount.append(pin)
            files_by_skill = self.skill_repository.get_files_for_skill_versions(pins_to_mount)
            for pin in pins_to_mount:
                if pin.skill_id not in files_by_skill:
                    logger.warning(
                        "Agent %s skill %s pinned version %s has no files; the version may have been removed",
                        agent.id,
                        pin.skill_id,
                        pin.version,
                    )
            skills_json, collisions = build_skills_manifest(mounted_skills, files_by_skill)
            for collision in collisions:
                # Two skills claiming one workspace path: the loser's file is silently
                # absent for the agent, so surface it rather than letting the agent
                # fail to find documentation it was told exists.
                logger.warning("Agent %s skill file collision: %s", agent.id, collision)
        tools_md = rendered.tools_md + self._build_skill_pointers(mounted_skills) + build_tool_context_md(decrypted)
        # AGENTS.md is auto-loaded into the startup prompt by both runtimes, so the
        # --profile mapping + no-fallback policy is appended here (not just to TOOLS.md).
        # The chat-commands and role-scope policies ride along unconditionally — they
        # apply to every agent, integrations or not, and to custom templates we don't
        # control.
        # Credential-free tools ride in their own block: the integrations policy is built
        # from configured secrets, so a tool with no provider would otherwise be invisible
        # in the auto-loaded prompt no matter that its skill is mounted.
        # gog gets its own block: the aai-cli one insists on --profile and on aai-cli
        # being the only route to its integrations, neither of which is true of gog.
        agents_md = (
            rendered.agents_md
            + build_integrations_policy_md(decrypted)
            + build_gog_policy_md(gws_content if isinstance(gws_content, GoogleWorkspaceContent) else None)
            + build_local_tools_policy_md(s.name for s in mounted_skills)
            + build_chat_commands_policy_md()
            + build_role_scope_policy_md()
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
                agents_md=agents_md,
                boot_md=rendered.boot_md,
                heartbeat_md=rendered.heartbeat_md,
                hermes_config=hermes_cfg,
                aai_cli_config_toml=aai_config_toml,
                aai_cli_setup_sh=aai_setup_sh,
                gog_setup_sh=gog_setup_sh,
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
                agents_md=agents_md,
                boot_md=rendered.boot_md,
                bootstrap_md=rendered.bootstrap_md,
                heartbeat_md=rendered.heartbeat_md,
                openclaw_config_overlay=overlay,
                aai_cli_config_toml=aai_config_toml,
                aai_cli_setup_sh=aai_setup_sh,
                gog_setup_sh=gog_setup_sh,
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
        # Pin what this pod was started on. The runtime reads its config once, so this
        # is the model it serves until someone restarts it — however the Organization
        # default moves in the meantime.
        agent.running_model = effective_model
        agent.ingest_key_encrypted = encrypt_token(ingest_key, self.config.agent_token_encryption_key)
        agent.communication_key_encrypted = encrypt_token(
            communication_key,
            self.config.agent_token_encryption_key,
        )
        result = self.repository.save_with_lifecycle_event(
            agent,
            event_name=AGENT_STARTED,
            actor=actor,
            previous_status=previous_status,
            new_status=AgentStatus.RUNNING.value,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return result.agent

    def get_agent_logs(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        tail_lines: int = 100,
    ) -> AgentLogsRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)

        latest_snapshot = self.repository.get_latest_log_snapshot(agent_id)
        has_snapshots = latest_snapshot is not None

        if agent.status == AgentStatus.RUNNING:
            log_text = self.k8s.read_pod_logs(
                f"agent-{agent.id}",
                self.config.k8s_namespace,
                tail_lines=tail_lines,
            )
            lines = log_text.splitlines() if log_text else []
            return AgentLogsRead(lines=lines, source="live", has_snapshots=has_snapshots)

        if latest_snapshot is None:
            return AgentLogsRead(lines=[], source="snapshot", has_snapshots=False)
        all_lines = latest_snapshot.log_text.splitlines()
        lines = all_lines[-tail_lines:]
        return AgentLogsRead(
            lines=lines,
            source="snapshot",
            has_snapshots=True,
            snapshot_id=latest_snapshot.id,
            session_started_at=latest_snapshot.session_started_at,
            session_ended_at=latest_snapshot.session_ended_at,
        )

    def stream_agent_logs(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        tail_lines: int = 0,
    ) -> Iterator[str]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        if agent.status != AgentStatus.RUNNING:
            return iter(())
        return self.k8s.stream_pod_logs(
            f"agent-{agent.id}",
            self.config.k8s_namespace,
            tail_lines=tail_lines,
        )

    def get_log_history(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        snapshot_id: UUID | None = None,
    ) -> AgentLogHistoryRead:
        self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)

        if snapshot_id is not None:
            snapshot = self.repository.get_snapshot_by_id(agent_id, snapshot_id)
        else:
            snapshot = self.repository.get_latest_log_snapshot(agent_id)

        if snapshot is None:
            return AgentLogHistoryRead(lines=[], has_more=False)

        older = self.repository.get_previous_snapshot(agent_id, snapshot.session_ended_at)
        return AgentLogHistoryRead(
            lines=snapshot.log_text.splitlines(),
            has_more=older is not None,
            session_ended_at=snapshot.session_ended_at,
            next_snapshot_id=older.id if older is not None else None,
        )

    def _capture_logs_before_stop(self, agent: Agent) -> None:
        try:
            log_text = self.k8s.read_pod_logs(
                f"agent-{agent.id}",
                self.config.k8s_namespace,
                tail_lines=50_000,
            )
            if not log_text:
                logger.info("No logs to capture for agent %s (empty response)", agent.id)
                return
            encoded = log_text.encode("utf-8")
            if len(encoded) > _MAX_LOG_SNAPSHOT_BYTES:
                truncated = encoded[-_MAX_LOG_SNAPSHOT_BYTES:]
                log_text = truncated.decode("utf-8", errors="replace")
                idx = log_text.find("\n")
                if idx > 0:
                    log_text = log_text[idx + 1 :]
            now = dt.datetime.now(dt.UTC)
            byte_size = len(log_text.encode("utf-8"))
            self.repository.save_log_snapshot(
                AgentLogSnapshot(
                    agent_id=agent.id,
                    session_started_at=agent.updated_at,
                    session_ended_at=now,
                    log_text=log_text,
                    byte_size=byte_size,
                )
            )
            self.repository.delete_old_snapshots(agent.id, keep=5)
            logger.info("Captured log snapshot for agent %s (%d bytes)", agent.id, byte_size)
        except Exception:
            logger.warning(
                "Failed to capture logs before stop for agent %s",
                agent.id,
                exc_info=True,
            )

    def stop_agent(self, agent_id: UUID, context: CurrentUserContext) -> AgentRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        stopped = self._stop_agent_unchecked(agent, resolve_actor_identity(context, agent.organization_id))
        return self._get_agent_read(stopped, context)

    def _stop_agent_unchecked(self, agent: Agent, actor: ActorIdentity) -> Agent:
        """Stop a known Agent after its caller has established authority."""

        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent {agent.id} is not running",
            )

        previous_status = agent.status.value
        self._capture_logs_before_stop(agent)
        name = f"agent-{agent.id}"
        ns = self.config.k8s_namespace
        self.k8s.delete_deployment(name, ns)
        self.k8s.delete_config_map(name, ns)
        self.k8s.delete_secret(name, ns)

        agent.status = AgentStatus.STOPPED
        agent.running_model = ""
        result = self.repository.save_with_lifecycle_event(
            agent,
            event_name=AGENT_STOPPED,
            actor=actor,
            previous_status=previous_status,
            new_status=AgentStatus.STOPPED.value,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return result.agent

    def rebuild_running_agents_for_maintenance(
        self, *, apply: bool
    ) -> tuple[list[Agent], list[tuple[Agent, Exception]]]:
        """Sequentially rebuild running Agent workloads for an operator maintenance task.

        This is intentionally an operator-only seam used by the cutover CLI; no HTTP
        route exposes this cross-Organization lifecycle authority.
        """
        agents = self.repository.find_all_running()
        if not apply:
            return agents, []
        actor = ActorIdentity(type=ActorIdentityType.SYSTEM, id="agent-maintenance")
        restarted: list[Agent] = []
        failures: list[tuple[Agent, Exception]] = []
        for agent in agents:
            try:
                stopped = self._stop_agent_unchecked(agent, actor)
                started = self._start_agent_unchecked(stopped, actor)
                if started.status != AgentStatus.RUNNING:
                    failures.append((agent, RuntimeError(f"restart completed with status {started.status.value}")))
                    continue
                restarted.append(started)
            except Exception as exc:
                logger.exception("Maintenance rebuild failed for agent %s", agent.id)
                failures.append((agent, exc))
        return restarted, failures

    def count_active_agents(self, organization_id: UUID) -> int:
        """Number of non-deleted agents in an org. Used by other domains (e.g. org
        deletion) to decide whether an org can be safely torn down."""
        return self.repository.count_active_by_org(organization_id)

    def delete_agent(self, agent_id: UUID, context: CurrentUserContext) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_DELETE)
        ns = self.config.k8s_namespace
        name = f"agent-{agent.id}"

        self.k8s.delete_deployment(name, ns)
        self.k8s.delete_service(name, ns)
        self.k8s.delete_pvc(name, ns)
        self.k8s.delete_secret(name, ns)
        self.k8s.delete_config_map(name, ns)

        delete_result = self.repository.soft_delete_with_event(
            agent,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delete_result.delivery_ids)

        if agent.litellm_key_encrypted:
            try:
                plaintext_key = decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
                self.litellm.block_key(plaintext_key)
            except Exception:
                logger.warning("Could not block LiteLLM key for agent %s", agent_id)

    def list_models(self, context: CurrentUserContext, catalog: bool = False) -> list[dict]:
        """Returns the allowlisted OpenRouter models as picker options.

        The Organization's resolved default model is guaranteed present, flagged
        is_default, and listed first, so the frontend and backend agree on which
        model an Agent inherits without a second request. It is normally already in
        the filtered list, since an Organization picks its default from its own
        allowlist; the append only fires for an Organization following a platform
        default its allowlist does not cover.
        """
        org_id = self._org_id(context)
        self.authorization.require_collection_scope(context, PermissionKey.AGENT_CREATE)
        raw_catalog = self.openrouter.list_models()

        if catalog:
            self.authorization.policy.require(
                context,
                org_id,
                PermissionKey.ORGANIZATION_UPDATE,
                detail="You don't have permission to view the full model catalog.",
            )
            allowed = raw_catalog
        else:
            allowed_models = self.organization_lookup.get_allowed_models(org_id)
            if allowed_models is None:
                raise HTTPException(status_code=404, detail="Organization not found")
            allowed = filter_models_by_allowlist(raw_catalog, allowed_models)
        options = [
            {
                "value": f"litellm/openrouter/{model['id']}",
                "label": model["name"],
                "contextLength": model.get("context_length"),
                "pricing": model.get("pricing"),
            }
            for model in allowed
        ]

        default_value = self.agent_settings_lookup.resolve_default_model(org_id)
        if default_value and not any(o["value"] == default_value for o in options):
            options.append(
                {
                    "value": default_value,
                    "label": default_value.removeprefix("litellm/openrouter/"),
                    "contextLength": None,
                    "pricing": None,
                }
            )

        # Stable sort puts the default first while preserving catalogue order.
        options.sort(key=lambda o: o["value"] != default_value)
        for option in options:
            option["isDefault"] = option["value"] == default_value
        return options

    def _backfill_google_client_credentials(self, decrypted: dict[SecretProvider, Any]) -> None:
        """Inject the server-owned OAuth client when a Google Workspace secret omits it.

        Backfill only when empty so a user-supplied client (the one the refresh token
        was issued under) keeps working.
        """
        content = decrypted.get(SecretProvider.GOOGLE_WORKSPACE)
        if isinstance(content, GoogleWorkspaceContent):
            if not content.client_id:
                content.client_id = self.config.google_cloud_client_id
            if not content.client_secret:
                content.client_secret = self.config.google_cloud_client_secret

    def _validate_live_integration(self, provider: SecretProvider, content: Any) -> None:
        """Validate submitted credentials with the provider before they are persisted.

        The browser can be modified, so any client-side preflight is advisory only. This
        method receives the exact content from the current request and runs the provider
        validator before Agent creation allocates a LiteLLM key or opens its persistence
        transaction. Providers without a live validator still receive schema validation;
        their credentials remain eligible for the existing on-demand validation endpoint.
        """
        validator = PROVIDER_VALIDATORS.get(provider)
        if validator is None:
            return

        validation_content = content
        if provider == SecretProvider.GOOGLE_WORKSPACE and isinstance(content, GoogleWorkspaceContent):
            # The stored payload may intentionally omit the deployment-owned OAuth client;
            # validate with the same server-side backfill used during runtime materialization
            # without changing the caller's encrypted payload.
            validation_content = content.model_copy(deep=True)
            self._backfill_google_client_credentials({provider: validation_content})

        try:
            result = validator(validation_content)
        except Exception as exc:
            logger.warning(
                "Live integration validation raised for provider %s (%s)",
                provider.value,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{PROVIDER_DISPLAY_NAMES[provider]} could not be validated; try again.",
            ) from exc

        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(result.error or f"{PROVIDER_DISPLAY_NAMES[provider]} credential is invalid."),
            )

    def validate_integration(self, agent_id: UUID, provider: SecretProvider, context: CurrentUserContext) -> dict:
        """Validate an existing secret on demand. Never persists — returns result directly."""
        org_id = self._org_id(context)
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
        secret = self.repository.get_secret(agent_id, provider)
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {provider.value} credential configured for this agent",
            )
        validator = PROVIDER_VALIDATORS.get(provider)
        if validator is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No validator available for {provider.value}",
            )
        if secret.shared_credential_id:
            shared = self.shared_credential_repository.get_by_ids_and_org([secret.shared_credential_id], org_id)
            if not shared:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced shared credential no longer exists",
                )
            ciphertext = shared[0].content
        else:
            ciphertext = secret.content
        assert ciphertext is not None
        content = decrypt_content(provider, ciphertext, self.config.agent_token_encryption_key)
        self._backfill_google_client_credentials({provider: content})
        result = validator(content)  # type: ignore[arg-type]
        return format_validation_result(result)

    def get_agent_health(self, agent_id: UUID, context: CurrentUserContext) -> AgentHealthRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)

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
            return AgentHealthRead(status="crashed", reason=friendly_pod_reason(pod_reason))
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
