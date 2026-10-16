"use client";

import { skipToken, useQuery } from "@tanstack/react-query";

import type { Agent, AgentHealth } from "@/features/agents/schemas";
import { agentsKey } from "@/features/agents/utils";

/**
 * The Agent the page beside the panel has loaded, read from the query cache without
 * fetching: every Agent route loads it already, and the panel also renders where no
 * Organization is active, so it cannot build an Organization-scoped request of its own.
 */
export function useCachedAgent(agentId: string | undefined): Agent | undefined {
  const { data } = useQuery<Agent>({ queryKey: agentsKey.detail(agentId ?? ""), queryFn: skipToken });
  return agentId ? data : undefined;
}

/** The health the Agent page polls, when it polls it. */
export function useCachedAgentHealth(agentId: string): AgentHealth | undefined {
  const { data } = useQuery<AgentHealth>({ queryKey: agentsKey.health(agentId), queryFn: skipToken });
  return data;
}
