"use client";

import { AppErrorState } from "@/components/app-error-state";
import { SkillDetailPage } from "@/features/skills/components/skill-detail-page";

import { useAgent } from "../hooks/use-agent";
import { canAgent } from "../utils";

/** Author/view one of this Agent's visible Skills (its own private lineage, or a
 * read-only Platform/Organization Skill it can fork). Thin wrapper: the shared
 * SkillDetailPage does the real work, scoped to this Agent. */
export function AgentSkillDetailPage({ agentId, skillId }: { agentId: string; skillId: string }) {
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

  return (
    <SkillDetailPage
      skillId={skillId}
      scope={{ kind: "agent", agentId: agent.id }}
      canManage={canAgent(agent, "agent.update")}
    />
  );
}
