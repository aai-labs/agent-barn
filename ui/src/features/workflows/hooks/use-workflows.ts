"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { ApiError } from "@/shared/api/error/errors";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  WorkflowCapabilitiesSchema,
  WorkflowListSchema,
  WorkflowSchema,
  WorkflowVersionListSchema,
  type Workflow,
  type WorkflowCapabilities,
  type WorkflowDraft,
  type WorkflowList,
  type WorkflowVersionList,
} from "../schemas";

/**
 * Reads stay fresh briefly so moving between the list, a definition and its
 * history does not refetch each time. Permissions can change at any moment, so
 * the window stays short; the API re-checks authority on every request and
 * every mutation, and access failures are never served from cache.
 */
const WORKFLOW_STALE_TIME = 30_000;

type WorkflowScope = { organizationId: string };
/** Which saved workflows a list shows: active ones, the viewer's own, or archived ones. */
export type WorkflowListFilter = "all" | "mine" | "archived";
export const workflowsKey = createQueryKeyStructure("workflows");
export const workflowKeys = {
  lists: (scope: WorkflowScope) => workflowsKey.listScope(scope),
  list: (scope: WorkflowScope, page: number, filter: WorkflowListFilter) =>
    workflowsKey.list({ scope, filters: { page, filter } }),
  /** Prefix of a definition and its version history. */
  detail: (scope: WorkflowScope, workflowId: string) =>
    [...workflowsKey.details(), scope, workflowId] as const,
  versions: (scope: WorkflowScope, workflowId: string) =>
    [...workflowKeys.detail(scope, workflowId), "versions"] as const,
  versionPage: (scope: WorkflowScope, workflowId: string, page: number) =>
    [...workflowKeys.versions(scope, workflowId), page] as const,
  capabilities: (scope: WorkflowScope) =>
    [...workflowsKey.all, "capabilities", scope] as const,
};

/** Workflows belong to the Organization, so its id alone scopes every read and key. */
function useScope() {
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  return {
    key: { organizationId },
    // Not useOrganizationApiBase, which throws: navigation also asks with no Organization.
    base: `/api/v1/organizations/${organizationId}`,
    enabled: Boolean(organizationId),
  };
}

const FILTER_QUERY: Record<WorkflowListFilter, string> = {
  all: "archived=false",
  mine: "archived=false&created_by_me=true",
  archived: "archived=true",
};

/** Saved definitions as card summaries; pass `enabled` only while the list is visible. */
export function useWorkflows(
  page: number,
  filter: WorkflowListFilter = "all",
  enabled = true,
) {
  const scope = useScope();
  return useQuery({
    queryKey: workflowKeys.list(scope.key, page, filter),
    enabled: scope.enabled && enabled,
    staleTime: WORKFLOW_STALE_TIME,
    queryFn: async () =>
      (
        await api.get<WorkflowList>(
          `${scope.base}/workflows?page=${page}&${FILTER_QUERY[filter]}`,
          { schema: WorkflowListSchema },
        )
      ).data,
  });
}
export function useWorkflow(workflowId: string) {
  const scope = useScope();
  return useQuery({
    queryKey: workflowKeys.detail(scope.key, workflowId),
    enabled: scope.enabled && Boolean(workflowId),
    staleTime: WORKFLOW_STALE_TIME,
    queryFn: async () =>
      (
        await api.get<Workflow>(`${scope.base}/workflows/${workflowId}`, {
          schema: WorkflowSchema,
        })
      ).data,
  });
}
export function useWorkflowVersions(workflowId: string, page: number) {
  const scope = useScope();
  return useQuery({
    queryKey: workflowKeys.versionPage(scope.key, workflowId, page),
    enabled: scope.enabled && Boolean(workflowId),
    staleTime: WORKFLOW_STALE_TIME,
    queryFn: async () =>
      (
        await api.get<WorkflowVersionList>(
          `${scope.base}/workflows/${workflowId}/versions?page=${page}`,
          { schema: WorkflowVersionListSchema },
        )
      ).data,
  });
}
/** Whether this installation offers workflows; every Member of the Organization may ask. */
export function useWorkflowCapabilities(enabled = true) {
  const scope = useScope();
  return useQuery({
    queryKey: workflowKeys.capabilities(scope.key),
    enabled: scope.enabled && enabled,
    staleTime: WORKFLOW_STALE_TIME,
    queryFn: async () =>
      (
        await api.get<WorkflowCapabilities>(
          `${scope.base}/workflow-capabilities`,
          { schema: WorkflowCapabilitiesSchema },
        )
      ).data,
  });
}
export function useWorkflowActions() {
  const scope = useScope();
  const client = useQueryClient();
  const invalidateLists = () =>
    client.invalidateQueries({ queryKey: workflowKeys.lists(scope.key) });
  // Lost authority, archive or another save means cached reads may be wrong.
  const refreshAfterFailure = (error: unknown, workflowId?: string) => {
    if (!(error instanceof ApiError) || ![403, 404, 409].includes(error.status))
      return;
    void invalidateLists();
    void client.invalidateQueries({
      queryKey: workflowKeys.capabilities(scope.key),
    });
    if (workflowId)
      void client.invalidateQueries({
        queryKey: workflowKeys.detail(scope.key, workflowId),
      });
  };
  // The response is the server's current definition, revision and allowed
  // actions for this actor, so it seeds the detail instead of a second read.
  const seed = async (workflow: Workflow) => {
    client.setQueryData(workflowKeys.detail(scope.key, workflow.id), workflow);
    await Promise.all([
      invalidateLists(),
      client.invalidateQueries({
        queryKey: workflowKeys.versions(scope.key, workflow.id),
      }),
    ]);
  };
  /** Creates a workflow, or saves a new version of an existing one. */
  const save = useMutation({
    mutationFn: async ({
      draft,
      workflowId,
      revision,
      defaultAgentId = null,
    }: {
      draft: WorkflowDraft;
      workflowId?: string;
      revision?: number;
      /** Only read when creating; an existing workflow changes it with `setDefaultAgent`. */
      defaultAgentId?: string | null;
    }) => {
      return (
        await api.post<Workflow>(
          workflowId
            ? `${scope.base}/workflows/${workflowId}/versions`
            : `${scope.base}/workflows`,
          workflowId
            ? { draft, expectedRevision: revision }
            : { draft, defaultAgentId },
          { schema: WorkflowSchema },
        )
      ).data;
    },
    onSuccess: seed,
    onError: (error, { workflowId }) => refreshAfterFailure(error, workflowId),
  });
  /** Changes which Agent a run starts with by default, without saving a new version. */
  const setDefaultAgent = useMutation({
    mutationFn: async ({
      workflowId,
      revision,
      defaultAgentId,
    }: {
      workflowId: string;
      revision: number;
      defaultAgentId: string | null;
    }) =>
      (
        await api.patch<Workflow>(
          `${scope.base}/workflows/${workflowId}`,
          { expectedRevision: revision, defaultAgentId },
          { schema: WorkflowSchema },
        )
      ).data,
    onSuccess: seed,
    onError: (error, { workflowId }) => refreshAfterFailure(error, workflowId),
  });
  const archive = useMutation({
    mutationFn: async ({
      workflowId,
      revision,
    }: {
      workflowId: string;
      revision: number;
    }) => {
      await api.post(`${scope.base}/workflows/${workflowId}/archive`, {
        expectedRevision: revision,
      });
      return workflowId;
    },
    onSuccess: (workflowId) =>
      Promise.all([
        invalidateLists(),
        client.invalidateQueries({
          queryKey: workflowKeys.detail(scope.key, workflowId),
        }),
      ]),
    onError: (error, { workflowId }) => refreshAfterFailure(error, workflowId),
  });
  return { save, setDefaultAgent, archive };
}
