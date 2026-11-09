"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedAgentTasksSchema, type AgentTaskStatus, type PaginatedAgentTasks } from "../schemas";
import { taskListParams, tasksKey } from "../utils";

/** Whose Tasks a list or board shows: one Agent's, or the Organization's, optionally narrowed to one Agent. */
export type TaskScope = { kind: "agent"; agentId: string } | { kind: "organization"; agentId: string | null };

/** Agents change their Tasks while people watch, so open lists catch up on their own. */
const TASKS_REFRESH_MS = 30_000;

function nextPage(lastPage: PaginatedAgentTasks) {
  return lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined;
}

/** The pages' Tasks, each once. Pages are by offset over the last change, so a Task that moved
 * up while pages loaded can come back on a later page; the first copy is kept. */
function uniqueTasks(pages: PaginatedAgentTasks[]) {
  const seen = new Set<string>();
  return pages.flatMap((page) => page.items).filter((task) => !seen.has(task.id) && Boolean(seen.add(task.id)));
}

/** Tasks in a scope, most recently changed first, optionally of one status. */
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
    refetchOnWindowFocus: true,
    refetchInterval: (current) => (current.state.error ? false : TASKS_REFRESH_MS),
  });
  return {
    tasks: query.data ? uniqueTasks(query.data.pages) : [],
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending && query.fetchStatus !== "idle",
    // Once Tasks are shown, a failed follow-up keeps them: only a first load that failed is an error.
    error: query.data ? null : query.error,
    loadMoreError: query.isFetchNextPageError ? query.error : null,
    refetch: query.refetch,
    hasMore: query.hasNextPage && !query.isFetchNextPageError,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}
