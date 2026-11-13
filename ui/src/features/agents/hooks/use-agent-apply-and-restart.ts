"use client";

import { useFetchAgent } from "./use-agent";
import { useStartAgent } from "./use-start-agent";
import { useStopAgent } from "./use-stop-agent";
import type { Agent } from "../schemas";

export function useAgentApplyAndRestart(
  agent: Pick<Agent, "id" | "status" | "updatedAt"> & Partial<Pick<Agent, "parentAgentId">>,
) {
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const fetchAgent = useFetchAgent();
  const podId = agent.parentAgentId ?? agent.id;

  async function applyAndRestart(
    apply: (stoppedAgent: Pick<Agent, "id" | "status" | "updatedAt">) => Promise<void>,
  ) {
    if (agent.status !== "RUNNING") {
      await apply(agent);
      return;
    }
    const stoppedPod = await stopAgent.mutateAsync(podId);
    try {
      await apply(agent.parentAgentId ? await fetchAgent(agent.id) : stoppedPod);
    } finally {
      // Complete the restart transition even when the update fails, so an
      // Agent that was stopped for the update does not remain stopped.
      await startAgent.mutateAsync(podId);
    }
  }

  return {
    applyAndRestart,
    isPending: stopAgent.isPending || startAgent.isPending,
  };
}
