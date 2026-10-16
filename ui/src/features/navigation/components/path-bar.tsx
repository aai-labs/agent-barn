"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Check, ChevronRight, ChevronsUpDown } from "lucide-react";

import { ShareIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import { AgentLifecycleMenu } from "@/features/agents/components/agent-lifecycle-menu";
import { AgentUpdateNotice } from "@/features/agents/components/agent-update-banner";
import { ShareDialog } from "@/features/agents/components/share-dialog";
import { useAgents } from "@/features/agents/hooks/use-agents";
import { useModels } from "@/features/agents/hooks/use-models";
import type { Agent, AgentHealth } from "@/features/agents/schemas";
import { canAgent, currentModelOf } from "@/features/agents/utils";

import { useCachedAgent, useCachedAgentHealth } from "../hooks/use-cached-agent";
import { useContextPanel } from "../hooks/use-context-panel";
import { useIsDesktop } from "../hooks/use-is-desktop";
import { useRailModel } from "../hooks/use-rail-model";
import { ContextSwitcher } from "./context-switcher";
import { UserMenu } from "./user-menu";

const AGENT_ROUTE = /^\/dashboard\/([^/]+)\/agents\/([^/]+)(?:\/(.*))?$/;

/**
 * The desktop path bar: where you are, as a path you can switch at each step. The
 * first step is the Organization (or Platform View), the second the Agent when you are
 * inside one (its avatar carries the status dot), and the last the page or section you
 * are on. Inside an Agent a chip with its status, runtime and model follows, beside
 * the update notice, lifecycle and Share actions it bears on; the account menu ends
 * the bar.
 */
export function PathBar() {
  const pathname = usePathname() ?? "";
  const panel = useContextPanel();
  const rail = useRailModel();
  const agentMatch = AGENT_ROUTE.exec(pathname);
  // Mounted on desktop only: phones show the Agent's header and actions on the page, and
  // two copies of the lifecycle and Share controls must not coexist.
  const isDesktop = useIsDesktop();

  // The deepest selected entry names the page: a section inside a context, otherwise
  // the rail destination.
  const current =
    panel?.groups
      .flatMap((group) => group.items.flatMap((item) => [item, ...(item.children ?? [])]))
      .filter((item) => item.active)
      .at(-1)?.label ?? (agentMatch ? undefined : rail.items.find((item) => item.active)?.label);

  if (!isDesktop) return null;

  return (
    <header
      className="sticky top-0 z-20 hidden h-14 flex-shrink-0 items-center gap-0.5 px-4 lg:flex"
      style={{ background: "var(--bg)", borderBottom: "1px solid var(--line)" }}
    >
      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-center gap-0.5">
        <ContextSwitcher />
        {agentMatch && (
          <>
            <Separator />
            <AgentSwitcher orgId={agentMatch[1]} agentId={agentMatch[2]} rest={agentMatch[3]} />
          </>
        )}
        {current && (
          <>
            <Separator />
            <span className="truncate px-2 text-[14px]" style={{ color: "var(--ink-3)" }} aria-current="page">
              {current}
            </span>
          </>
        )}
      </nav>
      {agentMatch && <AgentActions agentId={agentMatch[2]} />}
      <div className="ml-2">
        <UserMenu />
      </div>
    </header>
  );
}

function Separator() {
  return (
    <span aria-hidden className="px-0.5 text-[16px] font-light" style={{ color: "var(--ink-5)" }}>
      /
    </span>
  );
}

/**
 * The Agent step of the path: the current Agent, and a list of the team's Agents to
 * move to. Moving keeps the section or settings page you are on, so comparing two
 * Agents' logs is one switch, not a switch and a click.
 */
function AgentSwitcher({ orgId, agentId, rest }: { orgId: string; agentId: string; rest?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const agent = useCachedAgent(agentId);
  const { agents } = useAgents();
  const orgBase = `/dashboard/${orgId}`;

  // A connection or skill page belongs to the Agent it was opened from, so moving from
  // one lands on the other Agent's own page instead.
  const keepsPlace = !rest || rest === "configuration";
  const targetFor = (nextId: string) => {
    if (!keepsPlace) return `${orgBase}/agents/${nextId}`;
    const query = searchParams.toString();
    return `${orgBase}/agents/${nextId}${rest ? `/${rest}` : ""}${query ? `?${query}` : ""}`;
  };

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Switch agent. Current: ${agent?.name ?? "Agent"}`}
          className="af-hover-bg flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-[14px] font-semibold"
          style={{ color: "var(--ink)" }}
        >
          {agent && <AvatarWithStatus agent={agent} />}
          <span className="max-w-[220px] truncate">{agent?.name ?? "Agent"}</span>
          <ChevronsUpDown size={14} aria-hidden style={{ color: "var(--ink-4)" }} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="start" sideOffset={6} className="w-64">
        <DropdownMenuLabel>Agents</DropdownMenuLabel>
        {agents.map((candidate) => (
          <DropdownMenuItem
            key={candidate.id}
            onSelect={() => {
              if (candidate.id !== agentId) router.push(targetFor(candidate.id));
            }}
          >
            <AgentAvatar agent={candidate} size="xs" />
            <span className="flex-1 truncate">{candidate.name}</span>
            {candidate.id === agentId && <Check aria-label="Current" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href={orgBase}>
            <span className="flex-1">All agents</span>
            <ChevronRight aria-hidden />
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AgentActions({ agentId }: { agentId: string }) {
  const agent = useCachedAgent(agentId);
  if (!agent) return null;
  return <AgentActionButtons agent={agent} />;
}

function AgentActionButtons({ agent }: { agent: Agent }) {
  const [shareOpen, setShareOpen] = useState(false);
  const canManageLifecycle = canAgent(agent, "agent.lifecycle.manage");
  const canManageAccess = canAgent(agent, "agent.access.manage");

  return (
    <div className="flex flex-shrink-0 items-center gap-2">
      <AgentRuntimeChip agent={agent} />
      {canManageLifecycle && <AgentUpdateNotice agent={agent} />}
      {canManageLifecycle && <AgentLifecycleMenu agent={agent} />}
      {canManageAccess && (
        <>
          <button type="button" className="af-btn" onClick={() => setShareOpen(true)}>
            <ShareIcon /> Share
          </button>
          <ShareDialog
            agentId={agent.id}
            agentName={agent.name}
            organizationId={agent.organizationId}
            open={shareOpen}
            onOpenChange={setShareOpen}
          />
        </>
      )}
    </div>
  );
}

const RUNTIME_LABELS: Record<Agent["agentType"], string> = {
  hermes: "Hermes",
  openclaw: "OpenClaw",
};

/** How the Agent is doing and what it runs on, read-only and the same on every section. */
function AgentRuntimeChip({ agent }: { agent: Agent }) {
  const { models } = useModels();
  const health = useCachedAgentHealth(agent.id);
  const status = statusDot(agent, health);
  const model = currentModelOf(agent);
  // The Organization's model list names its models; a model outside it shows its id.
  const modelLabel =
    models.find((option) => option.value === model)?.label ?? model.split("/").at(-1) ?? model;

  return (
    <span
      title={`${status.label} · ${RUNTIME_LABELS[agent.agentType]} runtime, running ${model}`}
      className="inline-flex max-w-[340px] items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px]"
      style={{ border: "1px solid var(--line-strong)", color: "var(--ink-3)" }}
    >
      <span className="inline-flex flex-shrink-0 items-center gap-1.5 font-medium" style={{ color: status.color }}>
        <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: status.color }} />
        {status.label}
      </span>
      <span aria-hidden style={{ color: "var(--ink-5)" }}>
        ·
      </span>
      <span className="flex-shrink-0">{RUNTIME_LABELS[agent.agentType]}</span>
      <span aria-hidden style={{ color: "var(--ink-5)" }}>
        ·
      </span>
      <span className="truncate font-semibold" style={{ color: "var(--ink)" }}>
        {modelLabel}
      </span>
    </span>
  );
}

function statusDot(agent: Agent, health: AgentHealth | undefined) {
  if (agent.status === "ERROR" || health?.status === "crashed") {
    return { color: "var(--err)", label: "Needs attention" };
  }
  if (agent.status === "STOPPED") return { color: "var(--ink-4)", label: "Idle" };
  if (!health || health.status === "ok" || health.status === "starting" || health.status === "initializing") {
    return { color: "var(--ok)", label: health?.status === "ok" ? "Working" : "Initializing" };
  }
  return { color: "var(--warn)", label: "Disconnected" };
}

/** The Agent's avatar with its status as a dot, as StatusLine words it. */
function AvatarWithStatus({ agent }: { agent: Agent }) {
  const health = useCachedAgentHealth(agent.id);
  const dot = statusDot(agent, health);
  return (
    <span className="relative flex-shrink-0" title={dot.label}>
      <AgentAvatar agent={agent} size="xs" />
      <span
        aria-label={dot.label}
        role="img"
        className="absolute -bottom-px -right-px h-2 w-2 rounded-full"
        style={{ background: dot.color, boxShadow: "0 0 0 2px var(--bg)" }}
      />
    </span>
  );
}
