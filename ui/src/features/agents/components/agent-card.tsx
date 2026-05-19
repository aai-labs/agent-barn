"use client";

import type { Agent } from "../types";
import { fmtCost, getTemplate } from "../data";
import { AgentAvatar } from "./agent-avatar";
import { StatusLine } from "./status-line";

interface AgentCardProps {
  agent: Agent;
  onOpen: (agent: Agent) => void;
}

export function AgentCard({ agent, onOpen }: AgentCardProps) {
  return (
    <div
      className="af-card af-card-hover flex flex-col gap-5 p-[22px] pb-[18px] cursor-default min-h-[230px]"
      onClick={() => onOpen(agent)}
    >
      <div className="flex items-center gap-4">
        <AgentAvatar agent={agent} size="lg" />
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-[19px] tracking-tight" style={{ color: "var(--ink)" }}>
            {agent.name}
          </div>
          <div className="text-[13.5px] mt-0.5 font-mono" style={{ color: "var(--ink-3)" }}>
            {getTemplate(agent.template_id)?.slug ?? agent.template_id}
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col gap-2">
        <StatusLine status={agent.status} />
        <div
          className="text-[14px] leading-[1.45] line-clamp-2"
          style={{ color: "var(--ink-2)" }}
        >
          {agent.activity}
        </div>
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
        <div className="flex items-baseline gap-1.5 text-[13px]">
          <span style={{ color: "var(--ink-4)", fontSize: 12 }}>today</span>
          <span className="font-mono tabular-nums" style={{ color: "var(--ink)" }}>
            {fmtCost(agent.costToday)}
          </span>
        </div>
      </div>
    </div>
  );
}
