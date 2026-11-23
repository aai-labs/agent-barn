"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import {
  AnomalyOverrideSchema,
  AnomalyPageSchema,
  NormalBehaviourSchema,
  type AnomalyOverride,
  type AnomalyPage,
  type NormalBehaviour,
} from "../schemas";
import { anomaliesKey } from "../utils";

export const ANOMALY_PAGE_SIZE = 50;

/** The Agent's Anomalies, most recent first, a page at a time. */
export function useAgentAnomalies(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useInfiniteQuery({
    queryKey: anomaliesKey.list(organizationId, agentId),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const response = await api.get<AnomalyPage>(
        `${orgApiBase}/agents/${agentId}/anomalies?page=${pageParam}&page_size=${ANOMALY_PAGE_SIZE}`,
        { schema: AnomalyPageSchema },
      );
      return response.data;
    },
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: Boolean(organizationId && agentId),
  });

  return {
    anomalies: query.data?.pages.flatMap((page) => page.items),
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    hasMore: query.hasNextPage,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}

/** What counts as normal for the Agent, and the Owner's or Admin's adjustments to it. */
export function useAgentNormalBehaviour(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: anomaliesKey.normal(organizationId, agentId),
    queryFn: async () => {
      const response = await api.get<NormalBehaviour>(`${orgApiBase}/agents/${agentId}/normal-behaviour`, {
        schema: NormalBehaviourSchema,
      });
      return response.data;
    },
    enabled: Boolean(organizationId && agentId),
  });

  return { normal: query.data, isLoading: query.isPending, error: query.error, refetch: query.refetch };
}

export function useUpdateAnomalyOverride(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const queryClient = useQueryClient();
  const organizationId = selectedOrganization?.id ?? "";

  return useMutation({
    mutationFn: async (override: AnomalyOverride) => {
      const response = await api.put<AnomalyOverride>(`${orgApiBase}/agents/${agentId}/anomaly-override`, override, {
        schema: AnomalyOverrideSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      // Sensitivity moves every threshold the Normal behaviour section shows.
      void queryClient.invalidateQueries({ queryKey: anomaliesKey.agent(organizationId, agentId) });
    },
  });
}
