"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { TemplateReadSchema, type TemplateRead } from "../schemas";
import { templatesKey } from "../utils";

export function useUpdateTemplateFromPlatform() {
  const queryClient = useQueryClient();
  // Mounted by the published view for every scope, so resolve the org at call
  // time: Platform views have no active organization and must not throw on render.
  const { selectedOrganization } = useOrganizationContext();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      if (!selectedOrganization) {
        throw new Error("No active organization is available for an organization-scoped request");
      }
      const response = await api.post<TemplateRead>(
        `/api/v1/organizations/${selectedOrganization.id}/templates/${templateKey}/platform-update`,
        undefined,
        { schema: TemplateReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(templatesKey.detail(data.templateKey), data);
      void queryClient.invalidateQueries({ queryKey: templatesKey.lists() });
      void queryClient.invalidateQueries({ queryKey: templatesKey.detail(data.templateKey) });
    },
  });
}
