"use client";

import { useStartAgent } from "./use-start-agent";
import { useStopAgent } from "./use-stop-agent";
import type { Agent } from "../schemas";

export function useAgentApplyAndRestart(
  agent: Pick<Agent, "id" | "status">,
) {
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();

  async function applyAndRestart(apply: () => Promise<void>) {
    const wasRunning = agent.status === "RUNNING";
    if (!wasRunning) {
      await apply();
      return;
    }

    await stopAgent.mutateAsync(agent.id);
    try {
      await apply();
    } finally {
      // Complete the restart transition even when the update fails, so an
      // Agent that was stopped for the update does not remain stopped.
      await startAgent.mutateAsync(agent.id);
    }
  }

  return { applyAndRestart };
}
