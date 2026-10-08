"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import type { Agent, AgentHealth } from "../schemas";
import { canAgent, currentModelOf, formatModelName, isQuiet, isRecent } from "../utils";
import { useAgentHealth } from "../hooks/use-agent-health";
import { AgentAvatar } from "./agent-avatar";
import { AgentMetaBadges } from "./agent-meta-badges";

interface AgentCardProps {
  agent: Agent;
  href: string;
}

type Presence = { label: string; dot: string; badge: { bg: string; fg: string }; pulse?: boolean };

// Mirrors StatusLine's states as an avatar dot plus a badge.
function presenceOf(status: Agent["status"], health: AgentHealth | null | undefined, hasActivityPermission: boolean): Presence {
  if (status === "ERROR" || health?.status === "crashed") {
    return { label: "Needs attention", dot: "var(--err)", badge: { bg: "var(--err-soft)", fg: "var(--err)" } };
  }
  if (status === "STOPPED") {
    return { label: "Idle", dot: "var(--ink-4)", badge: { bg: "var(--warn-soft)", fg: "var(--warn)" } };
  }
  if (!hasActivityPermission) {
    return { label: "Running", dot: "var(--ok)", badge: { bg: "var(--bg-soft)", fg: "var(--ink-3)" } };
  }
  if (!health || health.status === "starting" || health.status === "initializing") {
    return { label: "Initializing", dot: "var(--ok)", pulse: true, badge: { bg: "var(--ok-soft)", fg: "var(--ok)" } };
  }
  if (health.status === "ok") {
    return { label: "Working", dot: "var(--ok)", badge: { bg: "color-mix(in srgb, var(--ok) 7%, var(--bg-elev))", fg: "var(--ok)" } };
  }
  return { label: "Disconnected", dot: "var(--warn)", badge: { bg: "var(--warn-soft)", fg: "var(--warn)" } };
}

export function AgentCard({ agent, href }: AgentCardProps) {
  const hasActivityPermission = canAgent(agent, "activity.read");
  const { health } = useAgentHealth(
    agent.id,
    agent.status === "RUNNING" && hasActivityPermission,
    30_000,
  );
  const presence = presenceOf(agent.status, health, hasActivityPermission);
  const creatorName = agent.creator?.fullName?.trim() || agent.creator?.email;
  const createdAt = new Date(agent.createdAt).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const lastMessage = agent.lastMessageAt ? new Date(agent.lastMessageAt) : null;
  const canReadActivity = hasActivityPermission && agent.lastMessageAt !== undefined;
  const model = currentModelOf(agent);

  let recencyColor = "var(--ink-3)";
  if (canReadActivity && (!lastMessage || isQuiet(agent.lastMessageAt))) recencyColor = "var(--warn)";
  else if (isRecent(agent.lastMessageAt)) recencyColor = "var(--ink)";

  return (
    <Link
      href={href}
      aria-label={`View ${agent.name}`}
      aria-describedby={`${agent.id}-status ${agent.id}-creator ${agent.id}-message`}
      className="group af-card af-card-hover flex min-h-48 flex-col overflow-hidden cursor-pointer no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-color)]"
    >
      <div className="p-4.5 pb-3.5">
        <div className="flex items-center gap-3">
          <span className="relative shrink-0">
            <AgentAvatar agent={agent} size="md" tone="soft" />
            <span
              aria-hidden="true"
              className={`absolute -right-px -bottom-px size-3 rounded-full border-[2.5px] ${presence.pulse ? "af-dot-pulse" : ""}`}
              style={{ background: presence.dot, borderColor: "var(--bg-elev)", color: presence.dot }}
            />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h3 className="m-0 min-w-0 truncate font-semibold text-base tracking-tight" title={agent.name} style={{ color: "var(--ink)" }}>
                {agent.name}
              </h3>
              <span id={`${agent.id}-status`} className="shrink-0">
                <span className="inline-block rounded-full px-2 py-px text-[0.68rem] font-medium" style={{ background: presence.badge.bg, color: presence.badge.fg }}>
                  {presence.label}
                </span>
              </span>
            </div>
            <div id={`${agent.id}-creator`} className="mt-0.5 flex min-w-0 whitespace-nowrap text-xs" style={{ color: "var(--ink-3)" }}>
              <span className="min-w-0 truncate" title={creatorName ? `Created by ${creatorName}` : undefined}>
                {creatorName ? <>By <span style={{ color: "var(--ink-2)" }}>{creatorName}</span></> : "Creator not recorded"}
              </span>
              <span className="shrink-0" title={`Created ${createdAt}`}>
                &nbsp;·&nbsp;<span className="sr-only">Created </span>{createdAt}
              </span>
            </div>
          </div>
        </div>

        <AgentMetaBadges agent={agent} className="mt-3.5 flex-wrap" />
        {model && (
          <div className="mt-2.5 truncate font-mono text-[0.72rem]" title={formatModelName(model)} style={{ color: "var(--ink-2)" }}>
            {formatModelName(model)}
          </div>
        )}
      </div>

      <div className="mt-auto flex items-baseline justify-between gap-3 px-4.5 py-3" style={{ background: "var(--bg)", borderTop: "1px solid var(--line)" }}>
        <div id={`${agent.id}-message`} className="flex min-w-0 items-baseline whitespace-nowrap">
          <span className="sr-only">Last message </span>
          <span className="shrink-0 text-[0.95rem] font-semibold tracking-tight" style={{ color: recencyColor }}>
            {!canReadActivity ? "Not available" : lastMessage ? formatDistanceToNowStrict(lastMessage, { addSuffix: true }) : "No messages yet"}
          </span>
          {canReadActivity && lastMessage && (
            <time
              dateTime={agent.lastMessageAt!}
              title={lastMessage.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" })}
              className="min-w-0 truncate text-xs opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
              style={{ color: "var(--ink-4)" }}
            >
              &nbsp;&nbsp;·&nbsp;&nbsp;{lastMessage.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}
            </time>
          )}
        </div>
        <ArrowUpRight size={16} aria-hidden="true" className="shrink-0 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" style={{ color: "var(--ink-3)" }} />
      </div>
    </Link>
  );
}
