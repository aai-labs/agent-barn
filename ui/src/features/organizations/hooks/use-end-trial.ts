"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { isSpendLimitQuery } from "../spend-limit";

import { type PlatformOrganization, PlatformOrganizationSchema } from "../schemas";
import { platformOrganizationsKey } from "../utils";

/** Ends a trial, moving it onto the spend limit given. */
export function useEndTrial(organizationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (limit: { budgetUsd: number; budgetDuration: string }) =>
      (
        await api.post<PlatformOrganization>(`/api/v1/platform/organizations/${organizationId}/end-trial`, limit, {
          schema: PlatformOrganizationSchema,
        })
      ).data,
    onSuccess: (organization) => {
      queryClient.setQueryData(platformOrganizationsKey.detail(organizationId), organization);
    },
    // Also on failure: when the new limit is saved but can't be applied yet, the trial
    // has still ended, and the page must show it.
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.all }),
        queryClient.invalidateQueries({ predicate: (query) => isSpendLimitQuery(query.queryKey) }),
      ]);
    },
  });
}
