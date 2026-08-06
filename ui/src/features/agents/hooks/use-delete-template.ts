"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { templatesKey } from "../utils";

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (templateKey: string) => {
      await api.delete(`${orgApiBase}/templates/${templateKey}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: templatesKey.all });
    },
  });
}
