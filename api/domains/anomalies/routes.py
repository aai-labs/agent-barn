from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.anomalies.models import (
    AgentAnomalyOverrideRead,
    AgentAnomalyOverrideUpdate,
    AgentAnomalyRead,
    AgentNormalBehaviourRead,
    AnomalyDetectionSettingsRead,
    AnomalyDetectionSettingsUpdate,
)
from api.domains.anomalies.service import AnomalyService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems, Pagination

anomalies_router = APIRouter(prefix="/organizations/{organization_id}", tags=["anomalies"])


@anomalies_router.get("/anomaly-detection", response_model=AnomalyDetectionSettingsRead)
def get_anomaly_detection(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AnomalyService, Injected(AnomalyService)],
):
    """Whether the Organization checks its Agents for unusual activity."""
    return service.get_settings(organization_id, context)


@anomalies_router.put("/anomaly-detection", response_model=AnomalyDetectionSettingsRead)
def update_anomaly_detection(
    organization_id: UUID,
    data: AnomalyDetectionSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AnomalyService, Injected(AnomalyService)],
):
    """Turn anomaly detection on or off for the Organization."""
    return service.update_settings(organization_id, data, context)


@anomalies_router.put("/agents/{agent_id}/anomaly-override", response_model=AgentAnomalyOverrideRead)
def set_anomaly_override(
    agent_id: UUID,
    data: AgentAnomalyOverrideUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AnomalyService, Injected(AnomalyService)],
):
    """Replace the Agent's sensitivity and hard caps."""
    return service.set_override(agent_id, data, context)


@anomalies_router.get("/agents/{agent_id}/anomalies", response_model=PaginatedItems[AgentAnomalyRead])
def list_anomalies(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AnomalyService, Injected(AnomalyService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """What was unusual about the Agent's activity, most recent first."""
    return service.list_anomalies(agent_id, context, Pagination(page=page, size=page_size))


@anomalies_router.get("/agents/{agent_id}/normal-behaviour", response_model=AgentNormalBehaviourRead)
def get_normal_behaviour(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AnomalyService, Injected(AnomalyService)],
):
    """The Agent's learned normal, what it used in its baseline window, and its override."""
    return service.normal_behaviour(agent_id, context)
