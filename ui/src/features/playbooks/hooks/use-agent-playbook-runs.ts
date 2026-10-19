"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  PaginatedPlaybookExtractionsSchema,
  PlaybookExtractionDetailSchema,
  PlaybookExtractionPreviewSchema,
  type PaginatedPlaybookExtractions,
  type PlaybookExtractionDetail,
  type PlaybookExtractionPreview,
} from "../schemas";
import { PLAYBOOK_RUNS_PAGE_SIZE, isActive, playbooksKey } from "../utils";

const POLL_INTERVAL_MS = 3_000;

/** One Agent's runs, newest first; polls while any run is queued or running. */
export function useAgentPlaybookRuns(agentId: string, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const query = useInfiniteQuery({
    queryKey: [...playbooksKey.agentRuns(agentId), orgApiBase],
    initialPageParam: 1,
    queryFn: async ({ pageParam }) =>
      (
        await api.get<PaginatedPlaybookExtractions>(
          `${orgApiBase}/agents/${agentId}/playbook-extractions?page=${pageParam}&page_size=${PLAYBOOK_RUNS_PAGE_SIZE}`,
          { schema: PaginatedPlaybookExtractionsSchema },
        )
      ).data,
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined,
    enabled,
    refetchInterval: (current) =>
      current.state.data?.pages.some((page) => page.items.some(isActive)) ? POLL_INTERVAL_MS : false,
  });
  const runs = query.data?.pages.flatMap((page) => page.items) ?? [];
  return {
    runs,
    hasActiveRun: runs.some(isActive),
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
    hasMore: query.hasNextPage,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}

/** What a run with these settings would read now. Calls no model. */
export function usePlaybookPreview(agentId: string, windowDays: number, maxSessions: number, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: playbooksKey.preview(agentId, orgApiBase, windowDays, maxSessions),
    queryFn: async () =>
      (
        await api.get<PlaybookExtractionPreview>(
          `${orgApiBase}/agents/${agentId}/playbook-extractions/preview?window_days=${windowDays}&max_sessions=${maxSessions}`,
          { schema: PlaybookExtractionPreviewSchema },
        )
      ).data,
    enabled,
    staleTime: 30_000,
    retry: false,
  });
  return {
    preview: query.data,
    isLoadingPreview: query.isPending && query.fetchStatus !== "idle",
    previewError: query.error,
    refetchPreview: query.refetch,
  };
}

/** One run with its generated playbook, loaded only when someone opens it. */
export function usePlaybookRun(agentId: string, runId: string | null) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: playbooksKey.run(agentId, runId ?? ""),
    queryFn: async () =>
      (
        await api.get<PlaybookExtractionDetail>(`${orgApiBase}/agents/${agentId}/playbook-extractions/${runId}`, {
          schema: PlaybookExtractionDetailSchema,
        })
      ).data,
    enabled: runId !== null,
  });
  return { run: query.data, isLoadingRun: query.isPending && query.fetchStatus !== "idle", runError: query.error };
}
