"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedEventDeliveriesSchema,
  type PaginatedEventDeliveries,
} from "../schemas";
import {
  EVENT_DELIVERIES_PAGE_SIZE,
  eventDeliveriesKey,
  mergeEventDeliveryPages,
  type EventDeliveryFilters,
} from "../utils";

export function useEventDeliveries(filters: EventDeliveryFilters) {
  const query = useInfiniteQuery({
    queryKey: eventDeliveriesKey.list({ scope: { mode: "infinite" }, filters }),
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams();
      params.set("page", String(pageParam));
      params.set("page_size", String(EVENT_DELIVERIES_PAGE_SIZE));
      params.set("sort", filters.sort);
      if (filters.search) params.set("search", filters.search);
      if (filters.status) params.set("status", filters.status);
      if (filters.organizationId)
        params.set("organization_id", filters.organizationId);
      if (filters.eventName) params.set("event_name", filters.eventName);
      if (filters.createdFrom) params.set("created_from", filters.createdFrom);
      if (filters.createdTo) params.set("created_to", filters.createdTo);

      const response = await api.get<PaginatedEventDeliveries>(
        `/api/v1/platform/event-deliveries?${params.toString()}`,
        { schema: PaginatedEventDeliveriesSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      return nextPage <= Math.ceil(lastPage.total / lastPage.pageSize)
        ? nextPage
        : undefined;
    },
  });

  return {
    deliveries: mergeEventDeliveryPages(query.data?.pages ?? []),
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending,
    isFetchingNextPage: query.isFetchingNextPage,
    isFetchingNextPageError: query.isFetchNextPageError,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    error: query.error,
    refetch: query.refetch,
  };
}
