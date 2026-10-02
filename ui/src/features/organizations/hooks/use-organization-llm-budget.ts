"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { toastError } from "@/shared/toast";
import { agentSettingsKey } from "@/features/agent-settings/utils";

import {
  type OrganizationLlmBudget,
  OrganizationLlmBudgetSchema,
} from "../schemas";
import { isSpendLimitQuery } from "../spend-limit";
import { organizationLlmBudgetKey } from "../utils";
import { useActiveOrgRole } from "./use-active-org-role";

/** The Organization's own view of its spend limit.
 *
 *  Served from a stored snapshot rather than the provider, so it costs a single
 *  local query on page load. Skipped entirely for members: the endpoint requires
 *  cost.read, so fetching would only ever produce a 403. */
export function useOrganizationLlmBudget() {
  const { canManage, selectedOrganization } = useActiveOrgRole();
  const organizationId = selectedOrganization?.id ?? null;

  const query = useQuery({
    queryKey: organizationLlmBudgetKey.detail(organizationId ?? ""),
    queryFn: async () => {
      const response = await api.get<OrganizationLlmBudget>(
        `/api/v1/organizations/${organizationId}/llm-budget`,
        { schema: OrganizationLlmBudgetSchema },
      );
      return response.data;
    },
    // Served from a stored snapshot refreshed on a schedule, so polling it on every
    // mount buys nothing.
    staleTime: 60_000,
    enabled: !!organizationId && canManage,
  });

  return { budget: query.data ?? null, isLoading: query.isPending, error: query.error, refetch: query.refetch };
}

/** Set or clear the Organization's own limit beneath its Spend Ceiling.
 *  `toastOnError: false` for callers that render the failure inline. */
export function useSetOrganizationOwnLlmBudget({ toastOnError = true }: { toastOnError?: boolean } = {}) {
  const { selectedOrganization } = useActiveOrgRole();
  const organizationId = selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (budgetUsd: number | null) => {
      const response = await api.put<OrganizationLlmBudget>(
        `/api/v1/organizations/${organizationId}/llm-budget`,
        { budgetUsd },
        { schema: OrganizationLlmBudgetSchema },
      );
      return response.data;
    },
    onSettled: () => {
      // Refetched on failure too: a 502 means the limit was stored and only applying
      // it failed, so the card must not keep showing the previous value.
      void queryClient.invalidateQueries({ queryKey: organizationLlmBudgetKey.detail(organizationId) });
      // A lower limit pulls the default Agent limit and any Agent's own limit down.
      void queryClient.invalidateQueries({ queryKey: agentSettingsKey.detail(organizationId) });
      void queryClient.invalidateQueries({ predicate: (query) => isSpendLimitQuery(query.queryKey) });
    },
    onError: toastOnError
      ? (error: Error) => {
          toastError(error, "We couldn't update your organization's spend limit");
        }
      : undefined,
  });
}
