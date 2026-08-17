"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedEventDeliveriesSchema, type PaginatedEventDeliveries } from "../schemas";
import { EVENT_DELIVERIES_PAGE_SIZE, eventDeliveriesKey, type EventDeliveryFilters } from "../utils";

export function useEventDeliveries(filters: EventDeliveryFilters, page: number) {
  return useQuery({
    queryKey: eventDeliveriesKey.list({ filters, page }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(EVENT_DELIVERIES_PAGE_SIZE));
      params.set("sort", filters.sort);
      if (filters.search) params.set("search", filters.search);
      if (filters.status) params.set("status", filters.status);
      if (filters.organizationId) params.set("organization_id", filters.organizationId);
      if (filters.eventName) params.set("event_name", filters.eventName);
      if (filters.createdFrom) params.set("created_from", filters.createdFrom);
      if (filters.createdTo) params.set("created_to", filters.createdTo);

      const response = await api.get<PaginatedEventDeliveries>(
        `/api/v1/platform/event-deliveries?${params.toString()}`,
        { schema: PaginatedEventDeliveriesSchema },
      );
      return response.data;
    },
  });
}
