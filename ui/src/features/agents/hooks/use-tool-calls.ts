"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { PaginatedToolCalls, PaginatedToolCallsSchema } from "../schemas";
import { toolCallsKey, TOOL_CALLS_PAGE_SIZE } from "../utils";

export interface ToolCallFilters {
  toolName: string;
  status: "" | "PENDING" | "SUCCESS" | "ERROR";
  fromDate: string;
  toDate: string;
}

export function useToolCalls(agentId: string, filters: ToolCallFilters, page: number) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: toolCallsKey.list({ agentId, ...filters, page }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(TOOL_CALLS_PAGE_SIZE));
      if (filters.toolName) params.set("tool_name", filters.toolName);
      if (filters.status) params.set("status", filters.status);
      if (filters.fromDate) params.set("from_date", toIso(filters.fromDate));
      if (filters.toDate) params.set("to_date", toIso(filters.toDate));

      const response = await api.get<PaginatedToolCalls>(
        `${orgApiBase}/agents/${agentId}/tool-calls?${params.toString()}`,
        { schema: PaginatedToolCallsSchema },
      );
      return response.data;
    },
    refetchInterval: page === 1 ? 5_000 : false,
  });
}

function toIso(localDatetime: string): string {
  return new Date(localDatetime).toISOString();
}
