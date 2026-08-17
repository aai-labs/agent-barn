"use client";

import { useStartAgent } from "./use-start-agent";
import { useStopAgent } from "./use-stop-agent";
import type { Agent } from "../schemas";

export function useAgentApplyAndRestart(
  agent: Pick<Agent, "id" | "status" | "updatedAt">,
) {
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();

  async function applyAndRestart(
    apply: (stoppedAgent: Pick<Agent, "id" | "status" | "updatedAt">) => Promise<void>,
  ) {
    const wasRunning = agent.status === "RUNNING";
    const stoppedAgent = wasRunning ? await stopAgent.mutateAsync(agent.id) : agent;
    if (!wasRunning) {
      await apply(stoppedAgent);
      return;
    }
    try {
      await apply(stoppedAgent);
    } finally {
      // Complete the restart transition even when the update fails, so an
      // Agent that was stopped for the update does not remain stopped.
      await startAgent.mutateAsync(agent.id);
    }
  }

  return {
    applyAndRestart,
    isPending: stopAgent.isPending || startAgent.isPending,
  };
}
