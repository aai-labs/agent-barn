"use client";

import type { Agent } from "../schemas";
import { AgentAboutProfile } from "./agent-about-profile";

// Spend lives on the Costs tab; About describes how the Agent is set up.
export function AboutTab({ agent }: { agent: Agent }) {
  return (
    <div className="flex flex-col gap-4">
      <AgentAboutProfile agent={agent} />
    </div>
  );
}
