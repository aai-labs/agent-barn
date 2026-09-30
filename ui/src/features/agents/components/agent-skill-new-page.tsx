"use client";

import { AppErrorState } from "@/components/app-error-state";
import { SkillNewPage } from "@/features/skills/components/skill-new-page";

import { useAgent } from "../hooks/use-agent";

/** Create a new Agent-private Skill lineage. Thin wrapper: the shared
 * SkillNewPage does the real work, scoped to this Agent. */
export function AgentSkillNewPage({ agentId }: { agentId: string }) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);

  if (isLoading) {
    return (
      <div className="af-page animate-pulse">
        <div className="h-6 w-56 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="mt-6 h-64 rounded-2xl" style={{ background: "var(--bg-soft)" }} />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="af-page">
        <AppErrorState error={error} title="We couldn't load this agent" onRetry={() => void refetch()} />
      </div>
    );
  }

  return <SkillNewPage scope={{ kind: "agent", agentId: agent.id }} />;
}
