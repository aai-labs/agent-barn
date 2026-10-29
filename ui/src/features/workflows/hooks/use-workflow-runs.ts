"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import {
  WorkflowRunHistorySchema,
  WorkflowRunListSchema,
  WorkflowRunSchema,
  isRunProgressing,
  type WorkflowRun,
  type WorkflowRunHistory,
  type WorkflowRunList,
} from "../run-schemas";
import { workflowsKey } from "./use-workflows";

const HISTORY_PAGE = 100;

function useRunScope(agentId: string) {
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  return {
    base: `${useOrganizationApiBase()}/agents/${agentId}`,
    key: [...workflowsKey.all, "runs", { organizationId, agentId }] as const,
    enabled: Boolean(organizationId && agentId),
  };
}

export function useWorkflowRuns(
  agentId: string,
  workflowId: string,
  page: number,
) {
  const scope = useRunScope(agentId);
  return useQuery({
    queryKey: [...scope.key, "list", workflowId, page],
    enabled: scope.enabled && Boolean(workflowId),
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.data?.items.some((run) => isRunProgressing(run.state))
        ? 3000
        : false,
    queryFn: async () =>
      (
        await api.get<WorkflowRunList>(
          `${scope.base}/workflow-runs?workflow_id=${workflowId}&page=${page}`,
          { schema: WorkflowRunListSchema },
        )
      ).data,
  });
}

export function useWorkflowRun(agentId: string, runId: string) {
  const scope = useRunScope(agentId);
  return useQuery({
    queryKey: [...scope.key, runId],
    enabled: scope.enabled && Boolean(runId),
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.data &&
      isRunProgressing(query.state.data.state)
        ? 3000
        : false,
    queryFn: async () =>
      (
        await api.get<WorkflowRun>(`${scope.base}/workflow-runs/${runId}`, {
          schema: WorkflowRunSchema,
        })
      ).data,
  });
}

export function useWorkflowRunHistory(
  agentId: string,
  runId: string,
  revision: number,
) {
  const scope = useRunScope(agentId);
  const read = async (page: number) =>
    (
      await api.get<WorkflowRunHistory>(
        `${scope.base}/workflow-runs/${runId}/history?page_size=${HISTORY_PAGE}&page=${page}`,
        { schema: WorkflowRunHistorySchema },
      )
    ).data;
  return useQuery({
    // Every history event bumps the run revision, so the key refetches exactly when it changes.
    queryKey: [...scope.key, runId, "history", revision],
    enabled: scope.enabled && Boolean(runId),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const first = await read(1);
      if (first.total <= HISTORY_PAGE) return first;
      // The API pages oldest first, so the newest events are on the last pages.
      const last = Math.ceil(first.total / HISTORY_PAGE);
      const pages = await Promise.all([read(last - 1), read(last)]);
      return { ...first, items: pages.flatMap((page) => page.items) };
    },
  });
}

export function useWorkflowRunActions(agentId: string) {
  const scope = useRunScope(agentId);
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: scope.key });
  const start = useMutation({
    mutationFn: async (payload: {
      workflowId: string;
      versionId: string;
      clientRequestId: string;
      inputs: Record<string, string | number | boolean>;
    }) =>
      (
        await api.post<WorkflowRun>(
          `${scope.base}/workflows/${payload.workflowId}/runs`,
          {
            versionId: payload.versionId,
            clientRequestId: payload.clientRequestId,
            inputs: payload.inputs,
          },
          { schema: WorkflowRunSchema },
        )
      ).data,
    onSuccess: async (run) => {
      client.setQueryData([...scope.key, run.id], run);
      await invalidate();
    },
  });
  const cancel = useMutation({
    mutationFn: async (run: WorkflowRun) =>
      (
        await api.post<WorkflowRun>(
          `${scope.base}/workflow-runs/${run.id}/cancel`,
          { expectedRevision: run.revision },
          { schema: WorkflowRunSchema },
        )
      ).data,
    onSettled: invalidate,
  });
  return { start, cancel };
}
