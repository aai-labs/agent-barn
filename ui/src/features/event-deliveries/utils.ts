import { createQueryKeyStructure } from "@/shared/query-keys";

import type { EventDeliverySortDirection, EventDeliveryStatus } from "./schemas";

export const EVENT_DELIVERIES_PAGE_SIZE = 50;

export const eventDeliveriesKey = createQueryKeyStructure("event-deliveries");
export const eventDeliveriesSummaryKey = createQueryKeyStructure(
  "event-deliveries-summary",
);
export const eventDeliveryEventTypesKey = createQueryKeyStructure(
  "event-deliveries-event-types",
);

export type EventDeliveryFilters = {
  search?: string;
  status?: EventDeliveryStatus;
  organizationId?: string;
  eventName?: string;
  createdFrom?: string;
  createdTo?: string;
  sort: EventDeliverySortDirection;
};
