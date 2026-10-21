"use client";

import { useIsDesktop } from "@/features/navigation/hooks/use-is-desktop";

import type { Agent } from "../schemas";
import { AgentAboutProfile } from "./agent-about-profile";

// Spend lives on the Costs tab; About describes how the Agent is set up.
export function AboutTab({ agent }: { agent: Agent }) {
  // The desktop path bar replaces the page header, so the Overview carries the avatar.
  const isDesktop = useIsDesktop();
  return (
    <div className="flex flex-col gap-4">
      <AgentAboutProfile agent={agent} profileHeader={isDesktop} />
    </div>
  );
}
