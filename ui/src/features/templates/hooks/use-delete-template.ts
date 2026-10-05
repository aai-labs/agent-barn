"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import { templatesKey } from "../utils";

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  // Mounted by the published view for every scope; resolve the org at call time so
  // Platform views (no active organization) don't throw on render.
  const { selectedOrganization } = useOrganizationContext();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      if (!selectedOrganization) {
        throw new Error("No active organization is available for an organization-scoped request");
      }
      await api.delete(`/api/v1/organizations/${selectedOrganization.id}/templates/${templateKey}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: templatesKey.all });
    },
  });
}
