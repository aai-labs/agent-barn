"use client";

import { useStartAgent } from "./use-start-agent";
import { useStopAgent } from "./use-stop-agent";

export function useRestartAgent() {
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();

  async function restart(agentId: string) {
    await stopAgent.mutateAsync(agentId);
    await startAgent.mutateAsync(agentId);
  }

  return { restart, isPending: stopAgent.isPending || startAgent.isPending };
}
