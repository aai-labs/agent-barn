"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
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

type WorkflowScope = { organizationId: string; agentId: string };
export const workflowsKey = createQueryKeyStructure("workflows");
export const workflowKeys = {
  lists: (scope: WorkflowScope) => workflowsKey.listScope(scope),
  list: (scope: WorkflowScope, page: number) =>
    workflowsKey.list({ ...scope, page }),
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

function useScope(agentId: string) {
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  return {
    key: { organizationId, agentId },
    base: `${useOrganizationApiBase()}/agents/${agentId}`,
    enabled: Boolean(organizationId && agentId),
  };
}

/** Saved definitions as card summaries; pass `enabled` only while the list is visible. */
export function useWorkflows(agentId: string, page: number, enabled = true) {
  const scope = useScope(agentId);
  return useQuery({
    queryKey: workflowKeys.list(scope.key, page),
    enabled: scope.enabled && enabled,
    staleTime: WORKFLOW_STALE_TIME,
    queryFn: async () =>
      (
        await api.get<WorkflowList>(`${scope.base}/workflows?page=${page}`, {
          schema: WorkflowListSchema,
        })
      ).data,
  });
}
export function useWorkflow(agentId: string, workflowId: string) {
  const scope = useScope(agentId);
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
export function useWorkflowVersions(
  agentId: string,
  workflowId: string,
  page: number,
) {
  const scope = useScope(agentId);
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
export function useWorkflowCapabilities(agentId: string, enabled = true) {
  const scope = useScope(agentId);
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
export function useWorkflowActions(agentId: string) {
  const scope = useScope(agentId);
  const client = useQueryClient();
  const invalidateLists = () =>
    client.invalidateQueries({ queryKey: workflowKeys.lists(scope.key) });
  // Lost access, archive or another save means cached reads may be wrong.
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
  const save = useMutation({
    mutationFn: async ({
      draft,
      workflowId,
      revision,
    }: {
      draft: WorkflowDraft;
      workflowId?: string;
      revision?: number;
    }) => {
      return (
        await api.post<Workflow>(
          workflowId
            ? `${scope.base}/workflows/${workflowId}/versions`
            : `${scope.base}/workflows`,
          workflowId ? { draft, expectedRevision: revision } : draft,
          { schema: WorkflowSchema },
        )
      ).data;
    },
    // The response is the server's current definition, revision and allowed
    // actions for this actor, so it seeds the detail instead of a second read.
    onSuccess: async (workflow) => {
      client.setQueryData(
        workflowKeys.detail(scope.key, workflow.id),
        workflow,
      );
      await Promise.all([
        invalidateLists(),
        client.invalidateQueries({
          queryKey: workflowKeys.versions(scope.key, workflow.id),
        }),
      ]);
    },
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
  return { save, archive };
}
