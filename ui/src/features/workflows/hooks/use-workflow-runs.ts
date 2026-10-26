"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  progressing: boolean,
) {
  const scope = useRunScope(agentId);
  return useQuery({
    queryKey: [...scope.key, runId, "history"],
    enabled: scope.enabled && Boolean(runId),
    refetchInterval: progressing ? 3000 : false,
    queryFn: async () =>
      (
        await api.get<WorkflowRunHistory>(
          `${scope.base}/workflow-runs/${runId}/history?page_size=100`,
          { schema: WorkflowRunHistorySchema },
        )
      ).data,
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
  // The server copies the version and inputs from the original run.
  const rerun = useMutation({
    mutationFn: async ({
      run,
      clientRequestId,
    }: {
      run: WorkflowRun;
      clientRequestId: string;
    }) =>
      (
        await api.post<WorkflowRun>(
          `${scope.base}/workflow-runs/${run.id}/re-run`,
          { clientRequestId },
          { schema: WorkflowRunSchema },
        )
      ).data,
    onSuccess: (run) => client.setQueryData([...scope.key, run.id], run),
    // A refused re-run may mean access was lost: refetch so errors replace cached content.
    onSettled: invalidate,
  });
  return { start, cancel, rerun };
}
