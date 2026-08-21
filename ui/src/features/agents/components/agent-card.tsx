"use client";

import type { Agent } from "../schemas";
import { currentModelOf, formatModelName } from "../utils";
import { ModelSourceBadge } from "./model-source-badge";
import { PendingModelNote } from "./pending-model-note";
import { useAgentHealth } from "../hooks/use-agent-health";
import { AgentAvatar } from "./agent-avatar";
import { AgentMetaBadges } from "./agent-meta-badges";
import { StatusLine } from "./status-line";

interface AgentCardProps {
  agent: Agent;
  onOpen: (agent: Agent) => void;
}

export function AgentCard({ agent, onOpen }: AgentCardProps) {
  const { health } = useAgentHealth(agent.id, agent.status === "RUNNING");

  return (
    <div
      className="af-card af-card-hover flex flex-col gap-5 p-5.5 pb-4.5 cursor-default min-h-[14.375rem]"
      onClick={() => onOpen(agent)}
    >
      <div className="flex items-start gap-4">
        <AgentAvatar agent={agent} size="lg" />
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-[1.1875rem] tracking-tight" style={{ color: "var(--ink)" }}>
            {agent.name}
          </div>
          {currentModelOf(agent) && (
            <>
              <div className="mt-0.5 flex items-center gap-1.5 text-[0.844rem]" style={{ color: "var(--ink-3)" }}>
                <span className="truncate font-mono">{formatModelName(currentModelOf(agent))}</span>
                <ModelSourceBadge source={agent.modelSource} />
              </div>
              <PendingModelNote pendingModel={agent.pendingModel} />
            </>
          )}
          {agent.slackConfig?.botDisplayName && (
            <div className="text-[0.813rem] mt-0.5 truncate" style={{ color: "var(--ink-4)" }}>
              @{agent.slackConfig.botDisplayName}
            </div>
          )}
          <AgentMetaBadges agent={agent} className="mt-2" />
        </div>
      </div>

      <div className="flex-1">
        <StatusLine status={agent.status} health={health} />
      </div>

      <div
        className="flex items-center justify-between pt-3.5"
        style={{ borderTop: "1px solid var(--line)" }}
      >
        <button
          className="af-btn af-btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(agent);
          }}
        >
          Open
        </button>
        <div className="text-xs tabular-nums" style={{ color: "var(--ink-4)" }}>
          {new Date(agent.createdAt).toLocaleDateString()}
        </div>
      </div>
    </div>
  );
}
