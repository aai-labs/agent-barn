"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import {
  CostFilterOptionSchema,
  OrganizationSpendSchema,
  PaginatedPlatformCostRecordsSchema,
  PlatformCostSummarySchema,
  type CostFilterOption,
  type OrganizationSpend,
  type PaginatedPlatformCostRecords,
  type PlatformCostSummary,
} from "../schemas";
import {
  COSTS_PAGE_SIZE,
  costFilterParams,
  mergePlatformCostPages,
  platformCostKey,
  type CostFilters,
} from "../utils";

const BASE = "/api/v1/platform/costs";
const OptionsSchema = z.array(CostFilterOptionSchema);
const OrganizationsSchema = z.array(OrganizationSpendSchema);

export function usePlatformCostSummary(filters: CostFilters) {
  const query = useQuery({
    queryKey: platformCostKey.list({ scope: { view: "summary" }, filters }),
    queryFn: async () => {
      const response = await api.get<PlatformCostSummary>(
        `${BASE}/summary?${costFilterParams(filters).toString()}`,
        { schema: PlatformCostSummarySchema },
      );
      return response.data;
    },
  });

  return {
    summary: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export function usePlatformCosts(filters: CostFilters) {
  const query = useInfiniteQuery({
    queryKey: platformCostKey.list({ scope: { mode: "infinite" }, filters }),
    queryFn: async ({ pageParam }) => {
      const params = costFilterParams(filters);
      params.set("page", String(pageParam));
      params.set("page_size", String(COSTS_PAGE_SIZE));
      const response = await api.get<PaginatedPlatformCostRecords>(
        `${BASE}?${params.toString()}`,
        { schema: PaginatedPlatformCostRecordsSchema },
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
    records: mergePlatformCostPages(query.data?.pages ?? []),
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

/**
 * Organizations ranked by spend, doubling as the organization filter's options.
 *
 * Sent without the organization filter itself: with it, picking an organization
 * would leave it as the only option and the filter could never be changed.
 */
export function usePlatformCostOrganizations(filters: CostFilters) {
  const scoped = { ...filters, organizationId: undefined };
  const query = useQuery({
    queryKey: platformCostKey.list({
      scope: { view: "filter-options", dimension: "organizations" },
      filters: scoped,
    }),
    queryFn: async () => {
      const response = await api.get<OrganizationSpend[]>(
        `${BASE}/organizations?${costFilterParams(scoped).toString()}`,
        { schema: OrganizationsSchema },
      );
      return response.data;
    },
  });

  return { organizations: query.data ?? [], isLoading: query.isPending };
}

export function usePlatformCostFilterOptions(filters: CostFilters) {
  const agentFilters = { ...filters, agentId: undefined };
  const modelFilters = { ...filters, model: undefined };

  const agents = useQuery({
    queryKey: platformCostKey.list({
      scope: { view: "filter-options", dimension: "agents" },
      filters: agentFilters,
    }),
    queryFn: async () => {
      const response = await api.get<CostFilterOption[]>(
        `${BASE}/filters/agents?${costFilterParams(agentFilters).toString()}`,
        { schema: OptionsSchema },
      );
      return response.data;
    },
  });

  const models = useQuery({
    queryKey: platformCostKey.list({
      scope: { view: "filter-options", dimension: "models" },
      filters: modelFilters,
    }),
    queryFn: async () => {
      const response = await api.get<CostFilterOption[]>(
        `${BASE}/filters/models?${costFilterParams(modelFilters).toString()}`,
        { schema: OptionsSchema },
      );
      return response.data;
    },
  });

  return {
    agentOptions: agents.data ?? [],
    modelOptions: models.data ?? [],
    isLoading: agents.isPending || models.isPending,
  };
}
