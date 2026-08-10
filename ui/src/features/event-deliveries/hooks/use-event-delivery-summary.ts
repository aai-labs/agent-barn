"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { EventDeliverySummarySchema, type EventDeliverySummary } from "../schemas";
import { eventDeliveriesSummaryKey } from "../utils";

export function useEventDeliverySummary() {
  const query = useQuery({
    queryKey: eventDeliveriesSummaryKey.all,
    queryFn: async () => {
      const response = await api.get<EventDeliverySummary>(
        "/api/v1/platform/event-deliveries/summary",
        { schema: EventDeliverySummarySchema },
      );
      return response.data;
    },
    // Manual refresh only (AF-247): no automatic polling.
    refetchInterval: false,
    refetchOnWindowFocus: false,
  });

  return {
    summary: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
