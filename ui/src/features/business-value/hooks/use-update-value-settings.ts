"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";

import {
  ValueSettingsSchema,
  type ValueSettings,
  type ValueSettingsUpdate,
} from "../schemas";
import { organizationValueKey, valueSettingsKey } from "../utils";

export function useUpdateValueSettings() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ValueSettingsUpdate) => {
      const response = await api.put<ValueSettings>(`${orgApiBase}/value-settings`, data, {
        schema: ValueSettingsSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: organizationValueKey.listScope({ organizationId }),
      });
      void queryClient.invalidateQueries({ queryKey: valueSettingsKey.detail(organizationId) });
    },
    onError: (error: Error) => {
      toastError(error, "Failed to save value settings. Please try again.");
    },
  });
}
