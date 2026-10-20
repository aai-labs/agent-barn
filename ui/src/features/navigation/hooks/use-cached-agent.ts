"use client";

import { useCallback, useSyncExternalStore } from "react";
import { hashKey, useQueryClient, type QueryKey } from "@tanstack/react-query";

import type { Agent, AgentHealth } from "@/features/agents/schemas";
import { agentsKey } from "@/features/agents/utils";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { workflowKeys } from "@/features/workflows/hooks/use-workflows";
import type { WorkflowCapabilities } from "@/features/workflows/schemas";

/**
 * What the query cache holds for a key, kept current, without fetching and without
 * becoming one of the query's observers.
 *
 * Navigation reads what the page beside it has loaded. It cannot fetch for itself: it
 * also renders where no Organization is active, so it cannot build an Organization-scoped
 * request. And it must not observe through `useQuery`: a query refetches with the options
 * of whichever observer set them last, so an observer with no query function (or
 * `skipToken`) could turn the page's own refetch, after a save invalidates the Agent,
 * into a "Missing queryFn" error.
 */
function useCachedData<T>(queryKey: QueryKey): T | undefined {
  const client = useQueryClient();
  const hash = hashKey(queryKey);
  const subscribe = useCallback(
    (onChange: () => void) =>
      client.getQueryCache().subscribe((event) => {
        if (event.query.queryHash === hash) onChange();
      }),
    [client, hash],
  );
  return useSyncExternalStore(
    subscribe,
    () => client.getQueryData<T>(queryKey),
    () => undefined,
  );
}

/** The Agent the page beside the panel has loaded. Every Agent route loads it already. */
export function useCachedAgent(agentId: string | undefined): Agent | undefined {
  const data = useCachedData<Agent>(agentsKey.detail(agentId ?? ""));
  return agentId ? data : undefined;
}

/** The health the Agent page polls, when it polls it. */
export function useCachedAgentHealth(agentId: string): AgentHealth | undefined {
  return useCachedData<AgentHealth>(agentsKey.health(agentId));
}

/**
 * Whether the platform offers workflow authoring to the Agent, as the Agent page has read
 * it. Unknown (false) until the page has asked, so Workflows joins the panel when the page
 * shows it.
 */
export function useCachedWorkflowAuthoring(agentId: string | undefined): boolean {
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const data = useCachedData<WorkflowCapabilities>(
    workflowKeys.capabilities({ organizationId, agentId: agentId ?? "" }),
  );
  return Boolean(agentId) && data?.authoring === true;
}
