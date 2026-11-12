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

/** Runs are addressed by their own id; the Agent that runs one is a filter or a field, never the path. */
function useRunScope() {
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  return {
    // Not useOrganizationApiBase, which throws: the navigation badge also runs with no Organization.
    base: `/api/v1/organizations/${organizationId}/workflow-runs`,
    key: [...workflowsKey.all, "runs", { organizationId }] as const,
    enabled: Boolean(organizationId),
  };
}

export type WorkflowRunFilters = {
  /** Only this Agent's runs. */
  agentId?: string;
  /** Only runs of this workflow. */
  workflowId?: string;
  /** `active` runs are still in flight; `settled` ones have ended. */
  status?: "active" | "settled";
  pageSize?: number;
};

const runQuery = (filters: WorkflowRunFilters, extra: Record<string, string>) => {
  const params = new URLSearchParams(extra);
  if (filters.agentId) params.set("agent_id", filters.agentId);
  if (filters.workflowId) params.set("workflow_id", filters.workflowId);
  if (filters.status) params.set("status", filters.status);
  if (filters.pageSize) params.set("page_size", String(filters.pageSize));
  return params.toString();
};

/** Runs on every Agent the viewer can read, newest first, narrowed by the filters. */
export function useWorkflowRuns(
  filters: WorkflowRunFilters,
  page: number,
  enabled = true,
) {
  const scope = useRunScope();
  return useQuery({
    queryKey: [...scope.key, "list", filters, page],
    enabled: scope.enabled && enabled,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      !query.state.error &&
      (filters.status === "active" ||
        query.state.data?.items.some((run) => isRunProgressing(run.state)))
        ? 3000
        : false,
    queryFn: async () =>
      (
        await api.get<WorkflowRunList>(
          `${scope.base}?${runQuery(filters, { page: String(page) })}`,
          { schema: WorkflowRunListSchema },
        )
      ).data,
  });
}

/** Reads the newest run of a workflow the viewer can see, on demand. */
export function useLatestWorkflowRun() {
  const scope = useRunScope();
  const client = useQueryClient();
  return async (workflowId: string) =>
    (
      await client.fetchQuery({
        queryKey: [...scope.key, "latest", workflowId],
        staleTime: 0,
        queryFn: async () =>
          (
            await api.get<WorkflowRunList>(
              `${scope.base}?${runQuery({ workflowId, pageSize: 1 }, {})}`,
              { schema: WorkflowRunListSchema },
            )
          ).data,
      })
    ).items[0] ?? null;
}

/**
 * Runs with a request awaiting a decision: the approvals inbox and its badge. With an
 * Agent, only that Agent's runs; without one, every Agent the viewer can read.
 */
export function useAwaitingApprovals(agentId?: string, enabled = true) {
  const scope = useRunScope();
  return useQuery({
    queryKey: [...scope.key, "awaiting-decision", agentId ?? "all"],
    enabled: scope.enabled && enabled,
    refetchOnWindowFocus: true,
    // A live request closes within minutes, so the inbox checks often.
    refetchInterval: (query) => (query.state.error ? false : 10_000),
    queryFn: async () =>
      (
        await api.get<WorkflowRunList>(
          `${scope.base}?${runQuery({ agentId, pageSize: 20 }, { awaiting_decision: "true" })}`,
          { schema: WorkflowRunListSchema },
        )
      ).data,
  });
}

export function useWorkflowRun(runId: string) {
  const scope = useRunScope();
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
        await api.get<WorkflowRun>(`${scope.base}/${runId}`, {
          schema: WorkflowRunSchema,
        })
      ).data,
  });
}

export function useWorkflowRunHistory(runId: string, revision: number) {
  const scope = useRunScope();
  return useQuery({
    // Every history event bumps the run revision, so the key refetches exactly when it changes.
    queryKey: [...scope.key, runId, "history", revision],
    enabled: scope.enabled && Boolean(runId),
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await api.get<WorkflowRunHistory>(
          `${scope.base}/${runId}/history?page_size=${HISTORY_PAGE}&newest_first=true`,
          { schema: WorkflowRunHistorySchema },
        )
      ).data,
  });
}

export function useWorkflowRunActions() {
  const scope = useRunScope();
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: scope.key });
  const start = useMutation({
    mutationFn: async (payload: {
      workflowId: string;
      /** The Agent chosen to run every step of this run. */
      agentId: string;
      versionId: string;
      title?: string;
      clientRequestId: string;
      inputs: Record<string, WorkflowInputValue>;
    }) =>
      (
        await api.post<WorkflowRun>(
          scope.base,
          {
            workflowId: payload.workflowId,
            agentId: payload.agentId,
            versionId: payload.versionId,
            ...(payload.title?.trim() ? { title: payload.title.trim() } : {}),
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
          `${scope.base}/${run.id}/cancel`,
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
          `${scope.base}/${run.id}/re-run`,
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
          `${scope.base}/${run.id}/approvals/${run.approval!.id}/decision`,
          { decision, ...(guidance?.trim() ? { guidance: guidance.trim() } : {}) },
          { schema: WorkflowRunSchema },
        )
      ).data,
    onSuccess: (run) => client.setQueryData([...scope.key, run.id], run),
    onSettled: invalidate,
  });
  return { start, cancel, rerun, decide };
}
