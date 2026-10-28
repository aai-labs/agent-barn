"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { PaginatedAgents, PaginatedAgentsSchema, type Agent } from "../schemas";
import { agentsKey } from "../utils";

const PAGE_SIZE = 100;

/**
 * Every Agent the viewer can see, read page by page, for views that name or filter by Agents
 * across the whole team rather than show its first page.
 */
export function useAllAgents() {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: [...agentsKey.all, "every-page", orgApiBase],
    queryFn: async () => {
      const agents: Agent[] = [];
      for (let page = 1; ; page++) {
        const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
        const { data } = await api.get<PaginatedAgents>(`${orgApiBase}/agents?${params.toString()}`, {
          schema: PaginatedAgentsSchema,
        });
        agents.push(...data.items);
        if (data.items.length === 0 || agents.length >= data.total) return agents;
      }
    },
  });
  return { agents: query.data ?? [], isLoading: query.isPending };
}
