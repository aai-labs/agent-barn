"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import type { Agent } from "../schemas";
import { canAgent, currentModelOf, formatModelName } from "../utils";
import { useAgentHealth } from "../hooks/use-agent-health";
import { AgentAvatar } from "./agent-avatar";
import { AgentMetaBadges } from "./agent-meta-badges";
import { ModelSourceBadge } from "./model-source-badge";
import { PendingModelNote } from "./pending-model-note";
import { StatusLine } from "./status-line";

interface AgentCardProps {
  agent: Agent;
  href: string;
}

export function AgentCard({ agent, href }: AgentCardProps) {
  const { health } = useAgentHealth(agent.id, agent.status === "RUNNING");
  const creatorName = agent.creator?.fullName?.trim() || agent.creator?.email;
  const lastMessage = agent.lastMessageAt ? new Date(agent.lastMessageAt) : null;
  const canReadActivity = canAgent(agent, "activity.read") && agent.lastMessageAt !== undefined;

  return (
    <Link
      href={href}
      aria-label={`View ${agent.name}`}
      aria-describedby={`${agent.id}-status ${agent.id}-creator ${agent.id}-message`}
      className="af-card af-card-hover flex min-h-56 flex-col overflow-hidden cursor-pointer no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-color)]"
    >
      <div className="flex flex-wrap items-start gap-3 p-4.5 pb-0">
        <div className="flex min-w-40 flex-1 items-start gap-3">
          <AgentAvatar agent={agent} size="md" tone="soft" />
          <div className="min-w-0 flex-1">
            <h3 className="m-0 line-clamp-2 font-semibold text-base tracking-tight break-words" title={agent.name} style={{ color: "var(--ink)" }}>
              {agent.name}
            </h3>
            <AgentMetaBadges agent={agent} className="mt-1.5 flex-wrap" />
          </div>
        </div>
        <div id={`${agent.id}-status`} className="ml-auto shrink-0 pt-1">
          <StatusLine status={agent.status} health={health} />
        </div>
      </div>

      <div className="px-4.5 pb-4 pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs" style={{ color: "var(--ink-3)" }}>
          <span id={`${agent.id}-creator`} className="min-w-0 truncate" title={creatorName ? `Created by ${creatorName}` : undefined}>
            {creatorName ? <>By <span style={{ color: "var(--ink-2)" }}>{creatorName}</span></> : "Creator not recorded"}
          </span>
          <span className="text-[0.68rem]">Created {new Date(agent.createdAt).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span>
        </div>
        {currentModelOf(agent) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[0.72rem]" style={{ color: "var(--ink-3)" }}>
            <span className="min-w-0 truncate font-mono">{formatModelName(currentModelOf(agent))}</span>
            <ModelSourceBadge source={agent.modelSource} />
          </div>
        )}
        <PendingModelNote pendingModel={agent.pendingModel} />
      </div>

      <div
        className="mt-auto flex min-h-24 items-center justify-between gap-3 px-4.5 py-3"
        style={{ background: "var(--bg)", borderTop: "1px solid var(--line)" }}
      >
        <div id={`${agent.id}-message`} className="min-w-0">
          <div className="mb-1 text-[0.68rem]" style={{ color: "var(--ink-3)" }}>Last message</div>
          <div className="text-base font-medium tracking-tight" style={{ color: "var(--ink)" }}>
            {!canReadActivity ? "Not available" : lastMessage ? formatDistanceToNowStrict(lastMessage, { addSuffix: true }) : "No messages yet"}
          </div>
          {canReadActivity && lastMessage && (
            <time dateTime={agent.lastMessageAt!} className="mt-1 block text-[0.68rem]" style={{ color: "var(--ink-3)" }}>
              {lastMessage.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" })}
            </time>
          )}
        </div>
        <ArrowUpRight size={18} aria-hidden="true" className="shrink-0" style={{ color: "var(--ink-3)" }} />
      </div>
    </Link>
  );
}
