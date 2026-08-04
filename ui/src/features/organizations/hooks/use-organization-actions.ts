"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";

import {
  type CreateOrganizationFormData,
  type OrganizationCreateResult,
  OrganizationCreateResultSchema,
  OrganizationSchema,
} from "../schemas";
import { organizationsKey } from "../utils";

export function useCreateOrganization() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateOrganizationFormData) => {
      const response = await api.post<OrganizationCreateResult>(
        "/api/v1/platform/organizations",
        data,
        { schema: OrganizationCreateResultSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
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
    },
  });
}
export function useUpdateOrganization() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      organizationId,
      data,
    }: {
      organizationId: string;
      data: Partial<{ name: string; description: string; allowedModels: string[] }>;
    }) => {
      const response = await api.patch<OrganizationCreateResult["organization"]>(
        `/api/v1/organizations/${organizationId}`,
        data,
        { schema: OrganizationSchema },
      );
      return response.data;
    },
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey.lists() });
      void queryClient.invalidateQueries({
        queryKey: organizationsKey.detail(variables.organizationId),
      });
      // The Hire Agent model picker (useModels) caches its result for an hour;
      // an allowlist change must be reflected immediately, not after a reload.
      if (variables.data.allowedModels !== undefined) {
        void queryClient.invalidateQueries({ queryKey: agentsKey.models() });
      }
    },
    onError: (error: Error) => {
      toastError(error, "Failed to save changes. Please try again.");
    },
  });
}
