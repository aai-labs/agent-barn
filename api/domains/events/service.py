from dataclasses import dataclass

from injector import inject, singleton

from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.models import (
    EventDeliveryFilter,
    EventDeliveryRead,
    EventDeliverySummaryRead,
    SupportedEventTypeRead,
)
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class EventDeliveryMonitorService:
    repository: OutboxMessageRepository

    def get_summary(self) -> EventDeliverySummaryRead:
        return self.repository.get_delivery_summary()

    def list_deliveries(
        self,
        delivery_filter: EventDeliveryFilter,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedItems[EventDeliveryRead]:
        return self.repository.find_delivery_explorer_page(
            delivery_filter=delivery_filter,
            pagination=Pagination(page=page, size=page_size),
        )

    def list_supported_event_types(self) -> list[SupportedEventTypeRead]:
        # Only event definitions with at least one intended Event Handler ever produce
        # an Event Delivery; a handler-less event (e.g. agent.created) can't appear in
        # this monitor and would be a dead filter option.
        grouped: dict[str, list[int]] = {}
        for definition in EVENT_REGISTRY.list_definitions():
            if not definition.handler_names:
                continue
            grouped.setdefault(definition.event_name, []).append(definition.schema_version)

        return [
            SupportedEventTypeRead(event_name=event_name, schema_versions=sorted(versions))
            for event_name, versions in sorted(grouped.items())
        ]
