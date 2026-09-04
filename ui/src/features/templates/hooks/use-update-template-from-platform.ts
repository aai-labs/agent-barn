"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { PlatformTemplateReadSchema, type PlatformTemplate } from "../schemas";
import { templatesKey } from "../utils";

export function useUpdateTemplateFromPlatform() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      const response = await api.post<PlatformTemplate>(
        `${orgApiBase}/templates/${templateKey}/platform-update`,
        undefined,
        { schema: PlatformTemplateReadSchema },
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
