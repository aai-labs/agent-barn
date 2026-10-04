"use client";

import type { Agent } from "@/features/agents/schemas";
import { canAgent } from "@/features/agents/utils";

import { MemoryItemsViewer } from "./memory-items-viewer";

export function AgentMemoryTab({ agent }: { agent: Agent }) {
  return <MemoryItemsViewer key={agent.id} agent={agent} enabled={canAgent(agent, "activity.read")} />;
}
