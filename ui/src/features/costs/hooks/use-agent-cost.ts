"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  AgentCostSchema,
  CostFilterOptionSchema,
  MonthlyCostListSchema,
  PaginatedCostRecordsSchema,
  type AgentCost,
  type CostFilterOption,
  type MonthlyCost,
  type PaginatedCostRecords,
} from "../schemas";
import {
  costFilterParams,
  costKey,
  monthlyCostParams,
  type CostFilters,
} from "../utils";

const OptionsSchema = z.array(CostFilterOptionSchema);

/** The filter one Agent's surface accepts. It has no agent or organization
 *  dimension: the server pins both from the Agent in the path. */
export type AgentCostFilters = Omit<CostFilters, "agentId" | "organizationId">;

// The Agent's reads authorize through its Agent Access Role, not the
// Organization-wide `cost.read`, so they are served under the Agent's own path
// rather than by the Organization routes with an agent filter.
function agentCostPath(orgApiBase: string, agentId: string, suffix = "") {
  return `${orgApiBase}/costs/agents/${agentId}${suffix}`;
}

function withQuery(path: string, params: URLSearchParams) {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

/** The summary params: the window and the narrowing filters, but no sort, which
 *  only orders the call list. */
function agentSummaryParams(filters: AgentCostFilters) {
  const params = costFilterParams(filters);
  params.delete("sort");
  return params;
}

/**
 * Spend, trend and breakdowns for one Agent.
 */
export function useAgentCost(agentId: string, filters: AgentCostFilters) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent", agentId },
      filters: { ...filters, sort: undefined },
    }),
    queryFn: async () => {
      const response = await api.get<AgentCost>(
        withQuery(agentCostPath(orgApiBase, agentId), agentSummaryParams(filters)),
        { schema: AgentCostSchema },
      );
      return response.data;
    },
  });

  return {
    agentCost: query.data ?? null,
    isLoadingAgentCost: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

/** Calls the Agent's Costs tab shows per page. Small on purpose: the list sits
 *  under the charts and monthly table, so it is a sample to page through rather
 *  than a feed to scroll. */
export const AGENT_CALLS_PAGE_SIZE = 10;

/** One page of the Agent's calls, under the same filter as its summary. */
export function useAgentCostCalls(
  agentId: string,
  filters: AgentCostFilters,
  page: number,
) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent-calls", agentId, page },
      filters,
    }),
    queryFn: async () => {
      const params = costFilterParams(filters);
      params.set("page", String(page));
      params.set("page_size", String(AGENT_CALLS_PAGE_SIZE));
      const response = await api.get<PaginatedCostRecords>(
        withQuery(agentCostPath(orgApiBase, agentId, "/calls"), params),
        { schema: PaginatedCostRecordsSchema },
      );
      return response.data;
    },
    // Keeps the current page on screen while the next one loads, so the table
    // holds its height instead of collapsing to a skeleton on every click.
    placeholderData: keepPreviousData,
  });

  return {
    records: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * The models this Agent used in the window.
 *
 * The model dimension is dropped from its own request, so choosing one model
 * leaves the others on offer instead of collapsing the list to the selection.
 */
export function useAgentCostModelOptions(
  agentId: string,
  filters: AgentCostFilters,
) {
  const orgApiBase = useOrganizationApiBase();
  const params = agentSummaryParams({ ...filters, model: undefined });
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent-filter-options", agentId, dimension: "models" },
      filters: { params: params.toString() },
    }),
    queryFn: async () => {
      const response = await api.get<CostFilterOption[]>(
        withQuery(agentCostPath(orgApiBase, agentId, "/filters/models"), params),
        { schema: OptionsSchema },
      );
      return response.data;
    },
  });

  return { modelOptions: query.data ?? [] };
}

/** Calendar-month totals for the Agent, under its filter but not its window. */
export function useAgentMonthlyCosts(
  agentId: string,
  filters: AgentCostFilters,
) {
  const orgApiBase = useOrganizationApiBase();
  const params = monthlyCostParams(filters);
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent-monthly", agentId },
      filters: { params: params.toString() },
    }),
    queryFn: async () => {
      const response = await api.get<MonthlyCost[]>(
        withQuery(agentCostPath(orgApiBase, agentId, "/monthly"), params),
        { schema: MonthlyCostListSchema },
      );
      return response.data;
    },
  });

  return {
    months: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
