"use client";

import type { Agent } from "../schemas";
import { canAgent } from "../utils";
import { useAgent } from "./use-agent";

const RESTART_PERMISSION = "agent.lifecycle.manage";

export function usePodAgent(agent: Agent | undefined) {
  const { agent: parent } = useAgent(agent?.parentAgentId ?? "");
  const pod = agent?.parentAgentId ? parent : agent;
  const restartsWithPod =
    !agent?.parentAgentId || canAgent(pod, RESTART_PERMISSION)
      ? agent
      : {
          ...agent,
          allowedActions: agent.allowedActions.filter((action) => action !== RESTART_PERMISSION),
        };
  return { pod, agent: restartsWithPod };
}
