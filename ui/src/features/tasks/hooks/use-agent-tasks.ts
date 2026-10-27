"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedAgentTasksSchema, type AgentTaskStatus, type PaginatedAgentTasks } from "../schemas";
import { taskListParams, tasksKey } from "../utils";

function nextPage(lastPage: PaginatedAgentTasks) {
  return lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined;
}

function pagedTasks(query: ReturnType<typeof useInfiniteQuery<PaginatedAgentTasks>>) {
  return {
    tasks: query.data?.pages.flatMap((page) => page.items) ?? [],
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
    hasMore: query.hasNextPage,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}

/** One Agent's Tasks, newest first, optionally of one status. */
export function useAgentTasks(agentId: string, status: AgentTaskStatus | null) {
  const orgApiBase = useOrganizationApiBase();
  const query = useInfiniteQuery({
    queryKey: tasksKey.agentTasks(agentId, orgApiBase, status),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) =>
      (
        await api.get<PaginatedAgentTasks>(
          `${orgApiBase}/agents/${agentId}/tasks?${taskListParams(pageParam as number, { status })}`,
          { schema: PaginatedAgentTasksSchema },
        )
      ).data,
    getNextPageParam: nextPage,
  });
  return pagedTasks(query);
}

/** Tasks across every Agent the viewer can read Tasks on, optionally of one Agent or status. */
export function useOrganizationTasks(agentId: string | null, status: AgentTaskStatus | null) {
  const orgApiBase = useOrganizationApiBase();
  const query = useInfiniteQuery({
    queryKey: tasksKey.organizationTasks(orgApiBase, agentId, status),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) =>
      (
        await api.get<PaginatedAgentTasks>(
          `${orgApiBase}/tasks?${taskListParams(pageParam as number, { agentId, status })}`,
          { schema: PaginatedAgentTasksSchema },
        )
      ).data,
    getNextPageParam: nextPage,
  });
  return pagedTasks(query);
}
