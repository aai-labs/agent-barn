"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedAgentTasksSchema, type AgentTaskStatus, type PaginatedAgentTasks } from "../schemas";
import { taskListParams, tasksKey } from "../utils";

/** Whose Tasks a list or board shows: one Agent's, or the Organization's, optionally narrowed to one Agent. */
export type TaskScope = { kind: "agent"; agentId: string } | { kind: "organization"; agentId: string | null };

function nextPage(lastPage: PaginatedAgentTasks) {
  return lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined;
}

/** Tasks in a scope, newest first, optionally of one status. */
export function useTasks(scope: TaskScope, status: AgentTaskStatus | null) {
  const orgApiBase = useOrganizationApiBase();
  const query = useInfiniteQuery({
    queryKey:
      scope.kind === "agent"
        ? tasksKey.agentTasks(scope.agentId, orgApiBase, status)
        : tasksKey.organizationTasks(orgApiBase, scope.agentId, status),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const url =
        scope.kind === "agent"
          ? `${orgApiBase}/agents/${scope.agentId}/tasks?${taskListParams(pageParam, { status })}`
          : `${orgApiBase}/tasks?${taskListParams(pageParam, { agentId: scope.agentId, status })}`;
      return (await api.get<PaginatedAgentTasks>(url, { schema: PaginatedAgentTasksSchema })).data;
    },
    getNextPageParam: nextPage,
  });
  return {
    tasks: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
    hasMore: query.hasNextPage,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}
