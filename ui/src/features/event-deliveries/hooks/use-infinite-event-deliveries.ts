"use client";

import { useCallback } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedEventDeliveriesSchema,
  type PaginatedEventDeliveries,
} from "../schemas";
import {
  EVENT_DELIVERIES_PAGE_SIZE,
  eventDeliveriesKey,
  type EventDeliveryFilters,
} from "../utils";

export function useInfiniteEventDeliveries(filters: EventDeliveryFilters) {
  const queryClient = useQueryClient();
  const queryKey = eventDeliveriesKey.list({ filters });

  const query = useInfiniteQuery({
    queryKey,
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams();
      params.set("page", String(pageParam));
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
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      const totalPages = Math.ceil(lastPage.total / lastPage.pageSize);
      return nextPage <= totalPages ? nextPage : undefined;
    },
  });

  // De-duplicate by Delivery ID: pages can shift between fetches as new deliveries
  // land, so naive flattening could otherwise render the same row twice.
  const seen = new Set<string>();
  const deliveries = (query.data?.pages.flatMap((page) => page.items) ?? []).filter((delivery) => {
    if (seen.has(delivery.id)) return false;
    seen.add(delivery.id);
    return true;
  });

  // Manual refresh (AF-247): clears every loaded page and re-fetches from page 1,
  // rather than a plain refetch() which would re-fetch every already-loaded page.
  const refresh = useCallback(() => {
    return queryClient.resetQueries({ queryKey });
  }, [queryClient, queryKey]);

  return {
    deliveries,
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isPending,
    error: query.error,
    refresh,
  };
}
