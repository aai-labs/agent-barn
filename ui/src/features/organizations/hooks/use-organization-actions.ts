"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";
import { agentsKey } from "@/features/agents/utils";
import { currentUserContextKey } from "@/auth/utils";

import {
  type CreateOrganizationFormData,
  OrganizationSchema,
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
