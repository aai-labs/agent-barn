"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SupportedEventTypesSchema, type SupportedEventType } from "../schemas";
import { eventDeliveryEventTypesKey } from "../utils";

export function useEventDeliveryEventTypes() {
  const query = useQuery({
    queryKey: eventDeliveryEventTypesKey.all,
    queryFn: async () => {
      const response = await api.get<SupportedEventType[]>(
        "/api/v1/platform/event-deliveries/event-types",
        { schema: SupportedEventTypesSchema },
      );
      return response.data;
    },
    staleTime: 5 * 60 * 1000,
  });

  return {
    eventTypes: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
