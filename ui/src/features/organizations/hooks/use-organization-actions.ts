"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";
import { agentsKey } from "@/features/agents/utils";
import { currentUserContextKey } from "@/auth/utils";

import type { CurrentUserContext } from "@/auth/schemas";
import type { ApiResult } from "@/shared/api/types";
import {
  type CreateOrganizationFormData,
  type PaginatedPlatformOrganizations,
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
      return organizationId;
    },
    onSuccess: (_, organizationId) => {
      // 1. Immediately remove from platform organizations infinite queries
      queryClient.setQueriesData<{
        pageParams: unknown[];
        pages: PaginatedPlatformOrganizations[];
      }>({ queryKey: platformOrganizationsKey.lists() }, (old) => {
        if (!old?.pages) return old;
        return {
          ...old,
          pages: old.pages.map((page) => ({
            ...page,
            items: page.items.filter((item) => item.id !== organizationId),
            total: Math.max(0, page.total - 1),
          })),
        };
      });

      // 2. Immediately remove from platform organizations all query (used by org switcher for admins)
      queryClient.setQueriesData<PaginatedPlatformOrganizations>(
        { queryKey: platformOrganizationsKey.list({ scope: { mode: "all" } }) },
        (old) => {
          if (!old?.items) return old;
          return {
            ...old,
            items: old.items.filter((item) => item.id !== organizationId),
            total: Math.max(0, old.total - 1),
          };
        },
      );

      // 3. Immediately remove from current user context (memberships)
      queryClient.setQueriesData<ApiResult<CurrentUserContext>>(
        { queryKey: currentUserContextKey.all },
        (old) => {
          if (!old?.data?.organizationUsers) return old;
          return {
            ...old,
            data: {
              ...old.data,
              organizationUsers: old.data.organizationUsers.filter(
                (m) => m.organizationId !== organizationId,
              ),
            },
          };
        },
      );

      // 4. Remove cached details for the deleted organization
      queryClient.removeQueries({
        queryKey: organizationsKey.detail(organizationId),
      });
      queryClient.removeQueries({
        queryKey: platformOrganizationsKey.detail(organizationId),
      });

      // 5. Invalidate queries to ensure background sync
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
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
