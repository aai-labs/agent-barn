"use client";

import { useEffect, useRef } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import {
  PaginatedRestorePoints,
  PaginatedRestorePointsSchema,
  type RestorePoint,
} from "../schemas";
import { agentsKey } from "../utils";

export const RESTORE_POINTS_PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 5_000;

const TERMINAL_STATUSES = new Set(["READY", "FAILED"]);

export function isRestorePointBusy(restorePoint: RestorePoint): boolean {
  return !TERMINAL_STATUSES.has(restorePoint.status);
}

/** Work outstanding on the server, so the list has a reason to keep asking. */
function hasOutstandingWork(restorePoint: RestorePoint): boolean {
  // A replay is owed after the row goes terminal, and reconciliation only runs on a
  // read — so polling has to outlast the status, or nothing would apply it.
  return isRestorePointBusy(restorePoint) || restorePoint.reapplyConfiguration;
}

/**
 * The API reconciles non-terminal rows against their Kubernetes Job on read, so
 * polling is what advances a capture — nothing moves off PENDING until somebody asks.
 */
function pagesOwingReplay(pages: PaginatedRestorePoints[] | undefined): boolean {
  return (pages ?? []).some((page) => page.items.some((item) => item.reapplyConfiguration));
}

export function useRestorePoints(agentId: string, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: agentsKey.restorePoints(agentId),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const response = await api.get<PaginatedRestorePoints>(
        `${orgApiBase}/agents/${agentId}/restore-points?page=${pageParam}&page_size=${RESTORE_POINTS_PAGE_SIZE}`,
        { schema: PaginatedRestorePointsSchema },
      );
      return response.data;
    },
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: enabled && !!agentId,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.items.some(hasOutstandingWork))
        ? POLL_INTERVAL_MS
        : false,
  });

  // A replay writes the Agent's template, skills and settings, and it finishes
  // without the browser asking for it. When the last one clears, everything showing
  // that configuration is out of date.
  const owed = pagesOwingReplay(query.data?.pages);
  const previouslyOwed = useRef(owed);
  useEffect(() => {
    if (previouslyOwed.current && !owed) {
      void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.configuration(agentId) });
    }
    previouslyOwed.current = owed;
  }, [agentId, owed, queryClient]);

  const pages = query.data?.pages ?? [];
  const first = pages[0];

  return {
    restorePoints: pages.flatMap((page) => page.items),
    total: first?.total ?? 0,
    cap: first?.cap ?? 0,
    manualCount: first?.manualCount ?? 0,
    // Before the first page arrives, cap and manualCount are placeholder zeros —
    // indistinguishable from an Agent with room to spare.
    hasCapacityData: first !== undefined,
    hasMore: query.hasNextPage,
    loadMore: () => void query.fetchNextPage(),
    isLoadingMore: query.isFetchingNextPage,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
