import { createQueryKeyStructure } from "@/shared/query-keys";

import type {
  EventDelivery,
  EventDeliverySortDirection,
  EventDeliveryStatus,
  PaginatedEventDeliveries,
} from "./schemas";

export const EVENT_DELIVERIES_PAGE_SIZE = 20;

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

/**
 * Offset pagination can overlap when new deliveries arrive between page reads.
 * Keep the most recently read representation of an ID, but only expose one row
 * per Event Delivery to consumers such as the virtualized list.
 */
export function mergeEventDeliveryPages(
  pages: readonly PaginatedEventDeliveries[],
): EventDelivery[] {
  const deliveriesById = new Map<string, EventDelivery>();
  for (const page of pages) {
    for (const delivery of page.items) {
      deliveriesById.set(delivery.id, delivery);
    }
  }
  return [...deliveriesById.values()];
}
