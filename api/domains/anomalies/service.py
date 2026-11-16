from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.anomalies.detection import Sensitivity
from api.domains.anomalies.models import (
    AgentAnomalyOverride,
    AgentAnomalyOverrideRead,
    AgentAnomalyOverrideUpdate,
    AnomalyDetectionSettingsRead,
    AnomalyDetectionSettingsUpdate,
)
from api.domains.anomalies.repository import Actor, AnomalySettingsRepository, OverrideValues
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy

READ_DENIED_DETAIL = "You don't have permission to view unusual activity in this organization."
MANAGE_DENIED_DETAIL = "You don't have permission to change how unusual activity is detected."


def override_read(override: AgentAnomalyOverride | None) -> AgentAnomalyOverrideRead:
    if override is None:
        return AgentAnomalyOverrideRead(
            sensitivity=Sensitivity.NORMAL, max_llm_tokens_per_hour=None, max_llm_calls_per_hour=None
        )
    return AgentAnomalyOverrideRead(
        sensitivity=Sensitivity(override.sensitivity),
        max_llm_tokens_per_hour=override.max_llm_tokens_per_hour,
        max_llm_calls_per_hour=override.max_llm_calls_per_hour,
    )


@inject
@singleton
@dataclass
class AnomalyService:
    """Who may see an Agent's Anomalies and adjust its normal: Organization Owners and
    Admins only, through `anomaly.read` and `anomaly.manage`.

    Agent routes resolve the Agent first, so an Agent the caller cannot see is a 404
    before the Organization Permission is checked (as for `agent.size.manage`).
    """

    settings_repository: AnomalySettingsRepository
    permission_policy: PermissionPolicy
    agent_authorization: AgentAuthorization
    organization_lookup: OrganizationLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> AnomalyDetectionSettingsRead:
        self.permission_policy.require(context, organization_id, PermissionKey.ANOMALY_READ, detail=READ_DENIED_DETAIL)
        return self._settings_read(organization_id, context)

    def update_settings(
        self, organization_id: UUID, data: AnomalyDetectionSettingsUpdate, context: CurrentUserContext
    ) -> AnomalyDetectionSettingsRead:
        self.permission_policy.require(
            context, organization_id, PermissionKey.ANOMALY_MANAGE, detail=MANAGE_DENIED_DETAIL
        )
        _settings, delivery_ids = self.settings_repository.set_enabled_with_event(
            organization_id,
            data.enabled,
            actor=self._actor(context, organization_id),
            subject_display=self.organization_lookup.get_name(organization_id),
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return self._settings_read(organization_id, context)

    def set_override(
        self, agent_id: UUID, data: AgentAnomalyOverrideUpdate, context: CurrentUserContext
    ) -> AgentAnomalyOverrideRead:
        agent = self._require_agent(agent_id, context, PermissionKey.ANOMALY_MANAGE, MANAGE_DENIED_DETAIL)
        override, delivery_ids = self.settings_repository.set_override_with_event(
            agent.organization_id,
            agent.id,
            OverrideValues(
                sensitivity=data.sensitivity.value,
                max_llm_tokens_per_hour=data.max_llm_tokens_per_hour,
                max_llm_calls_per_hour=data.max_llm_calls_per_hour,
            ),
            actor=self._actor(context, agent.organization_id),
            subject_display=agent.name,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return override_read(override)

    def _require_agent(
        self, agent_id: UUID, context: CurrentUserContext, permission: PermissionKey, detail: str
    ) -> Agent:
        agent = self.agent_authorization.require_visible(context, agent_id)
        self.permission_policy.require(context, agent.organization_id, permission, detail=detail)
        return agent

    def _settings_read(self, organization_id: UUID, context: CurrentUserContext) -> AnomalyDetectionSettingsRead:
        settings = self.settings_repository.get_settings(organization_id)
        return AnomalyDetectionSettingsRead(
            enabled=settings is not None and settings.enabled,
            can_manage=self.permission_policy.resolve(context, organization_id, PermissionKey.ANOMALY_MANAGE)
            is not None,
            updated_at=settings.updated_at if settings is not None else None,
        )

    @staticmethod
    def _actor(context: CurrentUserContext, organization_id: UUID) -> Actor:
        return Actor(
            identity=resolve_actor_identity(context, organization_id),
            display=context.user.full_name or context.user.email,
        )
