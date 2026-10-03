import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agent_settings.models import (
    AgentSettingsRead,
    AgentSettingsUpdate,
    DefaultModelSource,
)
from api.domains.agent_settings.repository import AgentSettingsRepository
from api.domains.agents.llm_budget import LOWERED_TO_FIT_ORGANIZATION, AgentLlmBudgetService
from api.domains.agents.repository import AgentRepository
from api.domains.agents.selection import is_model_allowed
from api.domains.auth.models import CurrentUserContext
from api.domains.events import ActorIdentity, EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.openrouter.client import OpenRouterClient

logger = logging.getLogger(__name__)

_OPENROUTER_MODEL_PREFIX = "litellm/openrouter/"


@inject
@singleton
@dataclass
class AgentSettingsService:
    """Organization-scoped defaults for Agents, starting with the runtime model.

    The default model is resolved rather than copied: an Agent with an empty `model`
    follows the Organization's default, and an Organization without its own default
    follows the platform's. Both indirections are read at Agent start, so changing a
    default moves exactly the Agents that inherit it and leaves explicit overrides
    alone.
    """

    repository: AgentSettingsRepository
    lookup: AgentSettingsLookupService
    agent_repository: AgentRepository
    organization_lookup: OrganizationLookupService
    openrouter: OpenRouterClient
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    agent_budgets: AgentLlmBudgetService

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> AgentSettingsRead:
        self._require_manage(organization_id, context)
        return self._read(organization_id, context)

    def update_settings(
        self,
        organization_id: UUID,
        data: AgentSettingsUpdate,
        context: CurrentUserContext,
    ) -> AgentSettingsRead:
        self._require_manage(organization_id, context)
        updated = data.model_dump(exclude_unset=True)
        if "default_agent_llm_budget_usd" in updated:
            # Checked before either write, so a request carrying both settings cannot
            # half-apply when the caller holds only one of the two permissions.
            self._require_budget_manage(organization_id, context)
        if "default_model" in updated:
            self._update_default_model(organization_id, updated["default_model"] or None, context)
        if "default_agent_llm_budget_usd" in updated:
            self._update_default_agent_llm_budget(organization_id, updated["default_agent_llm_budget_usd"], context)
        return self._read(organization_id, context)

    def _update_default_model(self, organization_id: UUID, candidate: str | None, context: CurrentUserContext) -> None:
        previous = self.lookup.get_default_model(organization_id)
        if candidate == previous:
            # No transition, so no Event: an audit trail of unchanged values is noise.
            return

        if candidate is not None:
            self._ensure_selectable_default(candidate, organization_id)

        inheriting, _ = self.agent_repository.count_by_model_source(organization_id)
        result = self.repository.set_default_model_with_event(
            organization_id,
            candidate,
            previous=previous,
            inheriting_agent_count=inheriting,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
            subject_display=self.organization_lookup.get_name(organization_id),
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)

    def _update_default_agent_llm_budget(
        self, organization_id: UUID, candidate: float | None, context: CurrentUserContext
    ) -> None:
        """The limit Agents without one of their own are held to.

        Refused above the Organization's own limit, like an Agent's own limit. Every
        inheriting Agent's key moves with it; Agents with their own limit do not.
        """
        previous = self.lookup.get_default_agent_llm_budget(organization_id)
        if candidate == previous:
            return
        organization = self.organization_lookup.get_llm_limit(organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        if candidate is not None and candidate > organization.limit_usd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                # No straight apostrophes: the settings surface renders a single-quoted
                # run of an error detail as a code identifier.
                detail=(
                    "The default agent spend limit cannot be more than the organization limit "
                    f"(${organization.limit_usd:,.2f})."
                ),
            )
        actor = resolve_actor_identity(context, organization_id)
        actor_display = context.user.full_name or context.user.email
        self._store_default_agent_llm_budget(
            organization_id, candidate, previous=previous, actor=actor, actor_display=actor_display, reason=None
        )

    def lower_default_agent_llm_budget(
        self, organization_id: UUID, limit_usd: float, *, actor: ActorIdentity, actor_display: str
    ) -> None:
        """Pull the Organization's own default Agent limit down to `limit_usd` if it is
        above it — the consequence of a lower Organization limit, not a request, so
        no permission check and the audit record says why."""
        previous = self.lookup.get_default_agent_llm_budget(organization_id)
        if previous is None or previous <= limit_usd:
            return
        self._store_default_agent_llm_budget(
            organization_id,
            limit_usd,
            previous=previous,
            actor=actor,
            actor_display=actor_display,
            reason=LOWERED_TO_FIT_ORGANIZATION,
        )

    def _store_default_agent_llm_budget(
        self,
        organization_id: UUID,
        amount_usd: float | None,
        *,
        previous: float | None,
        actor: ActorIdentity,
        actor_display: str,
        reason: str | None,
    ) -> None:
        before = self.agent_budgets.key_limits(organization_id)
        inheriting, _ = self.agent_budgets.count_by_source(organization_id)
        result = self.repository.set_default_agent_llm_budget_with_event(
            organization_id,
            amount_usd,
            previous=previous,
            inheriting_agent_count=inheriting,
            actor=actor,
            actor_display=actor_display,
            subject_display=self.organization_lookup.get_name(organization_id),
            reason=reason,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        self.agent_budgets.fit_to_organization(organization_id, before=before, actor=actor, actor_display=actor_display)

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_UPDATE,
            detail="You don't have permission to manage Agent Settings for this organization.",
        )

    def _require_budget_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.LLM_BUDGET_MANAGE,
            detail="You don't have permission to change spend limits for this organization.",
        )

    def _read(self, organization_id: UUID, context: CurrentUserContext) -> AgentSettingsRead:
        settings = self.repository.get_for_org(organization_id)
        own_default = settings.default_model if settings else None
        source: DefaultModelSource = "organization" if own_default else "platform"
        inheriting, override = self.agent_repository.count_by_model_source(organization_id)
        budget_inheriting, budget_override = self.agent_budgets.count_by_source(organization_id)
        organization = self.organization_lookup.get_llm_limit(organization_id)
        default_limit = self.lookup.resolve_default_agent_llm_budget(organization_id)
        return AgentSettingsRead(
            default_model=own_default,
            effective_default_model=self.lookup.resolve_default_model(organization_id),
            default_model_source=source,
            inheriting_agent_count=inheriting,
            override_agent_count=override,
            default_agent_llm_budget_usd=settings.default_agent_llm_budget_usd if settings else None,
            # Held beneath the Organization's own limit, as every inheriting key is.
            effective_default_agent_llm_budget_usd=(
                min(default_limit, organization.limit_usd) if organization else default_limit
            ),
            budget_inheriting_agent_count=budget_inheriting,
            budget_override_agent_count=budget_override,
            can_manage_llm_budget=self.permission_policy.resolve(
                context, organization_id, PermissionKey.LLM_BUDGET_MANAGE
            )
            is not None,
            updated_at=settings.updated_at if settings else None,
        )

    def _ensure_selectable_default(self, model: str, organization_id: UUID) -> None:
        """Two checks, because either alone leaves a hole.

        The allowlist keeps the default inside what the Organization permits, so an
        Agent that inherits it is never running a model the Organization disallows.
        But the allowlist holds globs — an Organization on `["*"]` would accept any
        string — so the candidate is also checked against the live catalogue. That
        second check is advisory: when OpenRouter is unreachable the save proceeds,
        matching how the allowlist editor itself degrades.
        """
        allowed_models = self.organization_lookup.get_allowed_models(organization_id)
        if allowed_models is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        if not is_model_allowed(model, allowed_models):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Model '{model.removeprefix(_OPENROUTER_MODEL_PREFIX)}' is not in the organization's "
                    "allowed model list. "
                    "Add it under Allowed Models before making it the default."
                ),
            )

        try:
            catalog = self.openrouter.list_models()
        except Exception as e:
            logger.warning("OpenRouter catalog unavailable, skipping default model validation: %s", e)
            return
        if not catalog:
            return
        # An exact match, not a glob: the allowlist holds patterns, but a default is
        # one concrete model the runtime will be pointed at.
        slug = model.removeprefix(_OPENROUTER_MODEL_PREFIX).lower()
        if not any(entry["id"].lower() == slug for entry in catalog):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Model '{model.removeprefix(_OPENROUTER_MODEL_PREFIX)}' does not match any known "
                    "models in the catalog."
                ),
            )
