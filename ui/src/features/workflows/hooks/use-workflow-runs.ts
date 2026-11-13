"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
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
  type WorkflowInputValue,
} from "../run-schemas";
import { workflowsKey } from "./use-workflows";

const HISTORY_PAGE = 100;

function useRunScope(agentId: string) {
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  return {
    // Not useOrganizationApiBase, which throws: the navigation badge also runs with no Organization.
    base: `/api/v1/organizations/${organizationId}/agents/${agentId}`,
    key: [...workflowsKey.all, "runs", { organizationId, agentId }] as const,
    enabled: Boolean(organizationId && agentId),
  };
}

/** Every run of this Agent across its workflows, newest first. */
export function useAgentRuns(agentId: string, page: number) {
  const scope = useRunScope(agentId);
  return useQuery({
    queryKey: [...scope.key, "list", "all", page],
    enabled: scope.enabled,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.data?.items.some((run) => isRunProgressing(run.state))
        ? 3000
        : false,
    queryFn: async () =>
      (
        await api.get<WorkflowRunList>(
          `${scope.base}/workflow-runs?page=${page}`,
          { schema: WorkflowRunListSchema },
        )
      ).data,
  });
}

/** Runs of this Agent with a request awaiting a decision: the approvals inbox and its badge. */
export function useAwaitingApprovals(agentId: string, enabled = true) {
  const scope = useRunScope(agentId);
  return useQuery({
    queryKey: [...scope.key, "awaiting-decision"],
    enabled: scope.enabled && enabled,
    refetchOnWindowFocus: true,
    // A live request closes within minutes, so the inbox checks often.
    refetchInterval: (query) => (query.state.error ? false : 10_000),
    queryFn: async () =>
      (
        await api.get<WorkflowRunList>(
          `${scope.base}/workflow-runs?awaiting_decision=true&page_size=20`,
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
  return useQuery({
    // Every history event bumps the run revision, so the key refetches exactly when it changes.
    queryKey: [...scope.key, runId, "history", revision],
    enabled: scope.enabled && Boolean(runId),
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await api.get<WorkflowRunHistory>(
          `${scope.base}/workflow-runs/${runId}/history?page_size=${HISTORY_PAGE}&newest_first=true`,
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
      inputs: Record<string, WorkflowInputValue>;
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
  // One verdict on one exact request; a stale or repeated decision is refused by the server.
  const decide = useMutation({
    mutationFn: async ({
      run,
      decision,
      guidance,
    }: {
      run: WorkflowRun;
      decision: "approve" | "decline";
      guidance?: string;
    }) =>
      (
        await api.post<WorkflowRun>(
          `${scope.base}/workflow-runs/${run.id}/approvals/${run.approval!.id}/decision`,
          { decision, ...(guidance?.trim() ? { guidance: guidance.trim() } : {}) },
          { schema: WorkflowRunSchema },
        )
      ).data,
    onSuccess: (run) => client.setQueryData([...scope.key, run.id], run),
    onSettled: invalidate,
  });
  return { start, cancel, rerun, decide };
}
