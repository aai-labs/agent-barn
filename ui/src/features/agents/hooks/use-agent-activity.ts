"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  AgentActivitySummarySchema,
  PaginatedAgentActivityCallsSchema,
  PaginatedAgentWakesSchema,
  type ActivityTrigger,
  type AgentActivitySummary,
  type PaginatedAgentActivityCalls,
  type PaginatedAgentWakes,
} from "../schemas";
import { agentsKey } from "../utils";

export const WAKES_PAGE_SIZE = 25;
export const ACTIVITY_CALLS_PAGE_SIZE = 50;

/** The window every activity read runs against, as the URL carries it. */
export type ActivityWindow = { fromDate?: string; toDate?: string };

function windowParams({ fromDate, toDate }: ActivityWindow): URLSearchParams {
  const params = new URLSearchParams();
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  return params;
}

export function useAgentActivity(agentId: string, activityWindow: ActivityWindow) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: agentsKey.activity(agentId, "summary", activityWindow),
    queryFn: async () => {
      const query = windowParams(activityWindow).toString();
      const response = await api.get<AgentActivitySummary>(
        `${orgApiBase}/agents/${agentId}/activity${query ? `?${query}` : ""}`,
        { schema: AgentActivitySummarySchema },
      );
      return response.data;
    },
    enabled: Boolean(agentId),
  });
}

export function useAgentWakes(
  agentId: string,
  activityWindow: ActivityWindow,
  trigger: ActivityTrigger | "",
  page: number,
) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: agentsKey.activity(agentId, "wakes", { ...activityWindow, trigger, page }),
    queryFn: async () => {
      const params = windowParams(activityWindow);
      params.set("page", String(page));
      params.set("page_size", String(WAKES_PAGE_SIZE));
      if (trigger) params.set("trigger", trigger);
      const response = await api.get<PaginatedAgentWakes>(
        `${orgApiBase}/agents/${agentId}/activity/wakes?${params.toString()}`,
        { schema: PaginatedAgentWakesSchema },
      );
      return response.data;
    },
    enabled: Boolean(agentId),
  });
}

export function useAgentActivityCalls(
  agentId: string,
  activityWindow: ActivityWindow,
  trigger: ActivityTrigger | "",
  page: number,
  enabled = true,
) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: agentsKey.activity(agentId, "calls", { ...activityWindow, trigger, page }),
    queryFn: async () => {
      const params = windowParams(activityWindow);
      params.set("page", String(page));
      params.set("page_size", String(ACTIVITY_CALLS_PAGE_SIZE));
      if (trigger) params.set("trigger", trigger);
      const response = await api.get<PaginatedAgentActivityCalls>(
        `${orgApiBase}/agents/${agentId}/activity/calls?${params.toString()}`,
        { schema: PaginatedAgentActivityCallsSchema },
      );
      return response.data;
    },
    enabled: enabled && Boolean(agentId),
  });
}
