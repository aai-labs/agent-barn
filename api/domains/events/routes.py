from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.events.models import (
    EventDeliveryFilter,
    EventDeliveryRead,
    EventDeliverySummaryRead,
    SupportedEventTypeRead,
    get_event_delivery_filter,
)
from api.domains.events.service import EventDeliveryMonitorService
from api.infrastructure.shared.models import PaginatedItems

# Global Platform View surface (AF-247): no Active Organization is resolved or
# accepted, and there is no Organization-scoped equivalent of this monitor.
event_delivery_monitor_router = APIRouter(prefix="/platform/event-deliveries", tags=["platform-event-deliveries"])


@event_delivery_monitor_router.get("/summary", response_model=EventDeliverySummaryRead)
def get_event_delivery_summary(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[EventDeliveryMonitorService, Injected(EventDeliveryMonitorService)],
):
    return service.get_summary()


@event_delivery_monitor_router.get("/event-types", response_model=list[SupportedEventTypeRead])
def get_event_delivery_event_types(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[EventDeliveryMonitorService, Injected(EventDeliveryMonitorService)],
):
    return service.list_supported_event_types()


@event_delivery_monitor_router.get("", response_model=PaginatedItems[EventDeliveryRead])
def get_event_deliveries(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    delivery_filter: Annotated[EventDeliveryFilter, Depends(get_event_delivery_filter)],
    service: Annotated[EventDeliveryMonitorService, Injected(EventDeliveryMonitorService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_deliveries(delivery_filter, page=page, page_size=page_size)
