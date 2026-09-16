"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";
import { agentsKey } from "@/features/agents/utils";
import { currentUserContextKey } from "@/auth/utils";

import {
  type CreateOrganizationFormData,
  OrganizationSchema,
  type OrganizationLlmCoverage,
  OrganizationLlmCoverageSchema,
  PlatformOrganizationSchema,
} from "../schemas";
import { organizationsKey, platformOrganizationsKey } from "../utils";

export function useCreateOrganization() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateOrganizationFormData) => {
      const response = await api.post(
        "/api/v1/organizations",
        data,
        { schema: OrganizationSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
    },
  });
}

export function useDeleteOrganization() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (organizationId: string) => {
      await api.delete(`/api/v1/organizations/${organizationId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
      // The org switcher reads its list from the user's memberships in
      // current-user-context, not from the queries above, so without this the
      // deleted organization stays selectable until a full page reload.
      void queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
    },
  });
}
/**
 * `toastOnError: false` for callers that render the failure inline — an allowlist edit
 * refused by a server-side guard names the Agents in the way, which belongs beside the
 * list being edited rather than in a banner that outlives the edit.
 */
export function useUpdateOrganization({ toastOnError = true }: { toastOnError?: boolean } = {}) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      organizationId,
      data,
    }: {
      organizationId: string;
      data: Partial<{ name: string; description: string; allowedModels: string[] }>;
    }) => {
      const response = await api.patch(
        `/api/v1/organizations/${organizationId}`,
        data,
        { schema: OrganizationSchema },
      );
      return response.data;
    },
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
      void queryClient.invalidateQueries({
        queryKey: organizationsKey.detail(variables.organizationId),
      });
      void queryClient.invalidateQueries({
        queryKey: platformOrganizationsKey.detail(variables.organizationId),
      });
      // The model pickers are built from the allowlist, so editing it changes what they
      // may offer. Scoped to allowlist edits: a rename has no bearing on the catalogue.
      // The key is a prefix, so both the allowlisted and full-catalogue variants refetch.
      if (variables.data.allowedModels) {
        void queryClient.invalidateQueries({ queryKey: agentsKey.models() });
      }
    },
    onError: toastOnError
      ? (error: Error) => {
          toastError(error, "Failed to save changes. Please try again.");
        }
      : undefined,
  });
}

/** Set or clear an Organization's LLM spend ceiling. Platform administrators only. */
export function useSetOrganizationLlmBudget(organizationId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (budget: { budgetUsd: number | null; budgetDuration?: string | null }) => {
      const response = await api.put(
        `/api/v1/platform/organizations/${organizationId}/llm-budget`,
        budget,
        { schema: PlatformOrganizationSchema },
      );
      return response.data;
    },
    onSettled: () => {
      // Refetched on failure too: a 502 here means the amount was stored and only the
      // proxy push failed, so the card must not keep rendering the previous value.
      void queryClient.invalidateQueries({
        queryKey: platformOrganizationsKey.detail(organizationId),
      });
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
    },
    onError: (error) => {
      toastError(error, "We couldn't update the LLM budget");
    },
  });
}

const llmCoverageKey = (organizationId: string) =>
  [...platformOrganizationsKey.detail(organizationId), "llm-coverage"] as const;

/** Read live from the proxy: a cached answer would keep claiming coverage after
 *  someone detached a key by hand. */
export function useOrganizationLlmCoverage(organizationId: string) {
  const query = useQuery({
    queryKey: llmCoverageKey(organizationId),
    queryFn: async () => {
      const response = await api.get<OrganizationLlmCoverage>(
        `/api/v1/platform/organizations/${organizationId}/llm-budget/coverage`,
        { schema: OrganizationLlmCoverageSchema },
      );
      return response.data;
    },
    enabled: !!organizationId,
  });

  return {
    coverage: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
  };
}

export function useEnrollOrganizationLlmKeys(organizationId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await api.post<OrganizationLlmCoverage>(
        `/api/v1/platform/organizations/${organizationId}/llm-budget/enroll`,
        {},
        { schema: OrganizationLlmCoverageSchema },
      );
      return response.data;
    },
    onSettled: () => {
      // Refetched on failure too: enrollment is partial by nature, so even a failed
      // run can have covered some Agents.
      void queryClient.invalidateQueries({ queryKey: llmCoverageKey(organizationId) });
    },
    onError: (error) => {
      toastError(error, "We couldn't enroll this organization's agents");
    },
  });
}
