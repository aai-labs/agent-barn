"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { CostFilterOptionSchema, type CostFilterOption } from "../schemas";
import { costFilterParams, costKey, type CostFilters } from "../utils";

import { z } from "zod";

const OptionsSchema = z.array(CostFilterOptionSchema);

/**
 * Agent and model options for the filter bar.
 *
 * The options are sent the same filters as everything else, so choosing a model
 * narrows the agent list to agents that used it. The dimension being chosen is
 * excluded from its own request — otherwise picking one agent would leave that
 * agent as the only option and the filter could never be changed, only cleared.
 */
export function useCostFilterOptions(filters: CostFilters) {
  const orgApiBase = useOrganizationApiBase();

  const agentFilters = { ...filters, agentId: undefined };
  const modelFilters = { ...filters, model: undefined };

  const agents = useQuery({
    queryKey: costKey.list({
      scope: { view: "filter-options", dimension: "agents" },
      filters: agentFilters,
    }),
    queryFn: async () => {
      const response = await api.get<CostFilterOption[]>(
        `${orgApiBase}/costs/filters/agents?${costFilterParams(agentFilters).toString()}`,
        { schema: OptionsSchema },
      );
      return response.data;
    },
  });

  const models = useQuery({
    queryKey: costKey.list({
      scope: { view: "filter-options", dimension: "models" },
      filters: modelFilters,
    }),
    queryFn: async () => {
      const response = await api.get<CostFilterOption[]>(
        `${orgApiBase}/costs/filters/models?${costFilterParams(modelFilters).toString()}`,
        { schema: OptionsSchema },
      );
      return response.data;
    },
  });

  return {
    agentOptions: agents.data ?? [],
    modelOptions: models.data ?? [],
    isLoading: agents.isPending || models.isPending,
  };
}
