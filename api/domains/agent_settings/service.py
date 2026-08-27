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
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import is_model_allowed
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
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

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> AgentSettingsRead:
        self._require_manage(organization_id, context)
        return self._read(organization_id)

    def update_settings(
        self,
        organization_id: UUID,
        data: AgentSettingsUpdate,
        context: CurrentUserContext,
    ) -> AgentSettingsRead:
        self._require_manage(organization_id, context)
        updated = data.model_dump(exclude_unset=True)
        if "default_model" not in updated:
            # Nothing addressed. Meaningful once further settings live alongside
            # this one, where a caller may send only the field it changed.
            return self._read(organization_id)

        candidate: str | None = updated["default_model"] or None
        previous = self.lookup.get_default_model(organization_id)
        if candidate == previous:
            # No transition, so no Event: an audit trail of unchanged values is noise.
            return self._read(organization_id)

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
        return self._read(organization_id)

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_UPDATE,
            detail="You don't have permission to manage Agent Settings for this organization.",
        )

    def _read(self, organization_id: UUID) -> AgentSettingsRead:
        settings = self.repository.get_for_org(organization_id)
        own_default = settings.default_model if settings else None
        source: DefaultModelSource = "organization" if own_default else "platform"
        inheriting, override = self.agent_repository.count_by_model_source(organization_id)
        return AgentSettingsRead(
            default_model=own_default,
            effective_default_model=self.lookup.resolve_default_model(organization_id),
            default_model_source=source,
            inheriting_agent_count=inheriting,
            override_agent_count=override,
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
