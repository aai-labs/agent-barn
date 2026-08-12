"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  type PlatformAgentStats,
  PlatformAgentStatsSchema,
  type PlatformMessageStats,
  PlatformMessageStatsSchema,
  type StatsFilters,
  type StatsRange,
} from "../schemas";
import { platformStatsKey } from "../utils";

function buildParams(filters: StatsFilters, range: StatsRange): string {
  const params = new URLSearchParams();
  if (filters.organizationId) params.set("organization_id", filters.organizationId);
  if (filters.platform) params.set("platform", filters.platform);
  if (range.fromDate) params.set("from_date", range.fromDate);
  if (range.toDate) params.set("to_date", range.toDate);
  return params.toString();
}

export function usePlatformMessageStats(
  filters: StatsFilters,
  range: StatsRange,
) {
  const query = useQuery({
    queryKey: platformStatsKey.list({
      scope: { resource: "messages" },
      filters: { ...filters, ...range },
    }),
    queryFn: async () => {
      const response = await api.get<PlatformMessageStats>(
        `/api/v1/platform/stats/messages?${buildParams(filters, range)}`,
        { schema: PlatformMessageStatsSchema },
      );
      return response.data;
    },
    placeholderData: keepPreviousData,
  });

  return {
    stats: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export function usePlatformAgentStats(
  filters: StatsFilters,
  range: StatsRange,
) {
  const query = useQuery({
    queryKey: platformStatsKey.list({
      scope: { resource: "agents" },
      filters: { ...filters, ...range },
    }),
    queryFn: async () => {
      const response = await api.get<PlatformAgentStats>(
        `/api/v1/platform/stats/agents?${buildParams(filters, range)}`,
        { schema: PlatformAgentStatsSchema },
      );
      return response.data;
    },
    placeholderData: keepPreviousData,
  });

  return {
    stats: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
