"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  type OrganizationLlmBudget,
  OrganizationLlmBudgetSchema,
} from "../schemas";
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
    queryKey: ["organizations", organizationId, "llm-budget"] as const,
    queryFn: async () => {
      const response = await api.get<OrganizationLlmBudget>(
        `/api/v1/organizations/${organizationId}/llm-budget`,
        { schema: OrganizationLlmBudgetSchema },
      );
      return response.data;
    },
    enabled: !!organizationId && canManage,
  });

  return { budget: query.data ?? null, isLoading: query.isPending };
}
