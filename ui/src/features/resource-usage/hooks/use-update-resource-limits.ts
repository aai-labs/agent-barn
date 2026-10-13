"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/shared/api";

import { ResourceLimitsSchema, type ResourceLimits, type ResourceLimitsUpdate } from "../schemas";
import { resourceUsageKey } from "../utils";

/**
 * Saves the namespace quota ceilings. The caller shows a failure inline, next to the field that
 * caused it, so there is no error toast here.
 */
export function useUpdateResourceLimits() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ResourceLimitsUpdate) => {
      const response = await api.put<ResourceLimits>("/api/v1/platform/resource-limits", data, {
        schema: ResourceLimitsSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      // The ceilings arrive inside the usage response, whatever range or filter it is for.
      void queryClient.invalidateQueries({ queryKey: resourceUsageKey.platformAll });
      toast.success("Namespace quota saved");
    },
  });
}
