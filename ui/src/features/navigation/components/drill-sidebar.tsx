"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, Menu } from "lucide-react";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import { useAgents } from "@/features/agents/hooks/use-agents";
import type { Agent } from "@/features/agents/schemas";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useContextPanel, type ContextPanelModel } from "../hooks/use-context-panel";
import { useRailModel } from "../hooks/use-rail-model";
import { ContextSwitcher } from "./context-switcher";
import { PanelGroups, PanelHeader, PanelLink } from "./context-panel";
import { UserMenu } from "./user-menu";

const SIDEBAR_AGENT_LIMIT = 8;

/**
 * C's one sidebar, on desktop. It never sits beside a second navigation column:
 * opening an Agent, its settings, Organization settings or Platform View drills the
 * same sidebar into that context, with a way back at its top.
 */
export function DrillSidebar() {
  const panel = useContextPanel();
  return (
    <aside
      aria-label="Navigation"
      className="sticky top-0 hidden h-screen w-[256px] flex-shrink-0 overflow-y-auto lg:block"
      style={{
        background: "var(--bg-soft)",
        borderRight: "1px solid var(--line)",
        borderTop: `3px solid ${panel?.tone === "platform" ? "var(--accent-color)" : "var(--bg-soft)"}`,
      }}
    >
      <DrillSidebarBody panel={panel} />
    </aside>
  );
}

/**
 * The phone's top bar for C: the sidebar opens as a drawer from the menu button, and
 * the bar names where you are.
 */
export function DrillMobileBar() {
  const panel = useContextPanel();
  const rail = useRailModel();
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const { selectedOrganization } = useOrganizationContext();
  // Remember the URL the drawer opened on: any navigation from inside it (a section,
  // an Agent, a switched Organization) then closes it.
  const routeKey = `${pathname}?${searchParams.toString()}`;
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const open = openedOn === routeKey;

  const active = panel?.groups
    .flatMap((group) => group.items.flatMap((item) => [item, ...(item.children ?? [])]))
    .filter((item) => item.active)
    .at(-1);
  const title = panel?.title ?? selectedOrganization?.name ?? "Agent Barn";
  const detail = panel ? active?.label : rail.items.find((item) => item.active)?.label;

  return (
    <header
      className="sticky top-0 z-30 flex h-14 flex-shrink-0 items-center gap-1 px-2 lg:hidden"
      style={{ background: "var(--bg)", borderBottom: "1px solid var(--line)" }}
    >
      <Sheet open={open} onOpenChange={(next) => setOpenedOn(next ? routeKey : null)}>
        <SheetTrigger asChild>
          <button
            type="button"
            aria-label="Open navigation"
            className="af-hover-bg grid h-11 w-11 flex-shrink-0 place-items-center rounded-lg"
            style={{ color: "var(--ink-2)" }}
          >
            <Menu size={20} aria-hidden />
          </button>
        </SheetTrigger>
        <SheetContent
          side="left"
          className="w-[300px] gap-0 overflow-y-auto p-0 sm:max-w-[300px]"
          style={{
            background: "var(--bg-soft)",
            borderTop: `3px solid ${panel?.tone === "platform" ? "var(--accent-color)" : "var(--bg-soft)"}`,
          }}
        >
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <div className="[&_a]:min-h-11 [&_button]:min-h-11">
            <DrillSidebarBody panel={panel} />
          </div>
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 items-center gap-1.5 px-1 text-[15px]" style={{ color: "var(--ink)" }}>
        <span className="truncate font-semibold">{title}</span>
        {detail && (
          <>
            <span aria-hidden style={{ color: "var(--ink-5)" }}>
              /
            </span>
            <span className="truncate" style={{ color: "var(--ink-2)" }}>
              {detail}
            </span>
          </>
        )}
      </div>
    </header>
  );
}

function DrillSidebarBody({ panel }: { panel: ContextPanelModel | null }) {
  const rail = useRailModel();
  const { selectedOrganization } = useOrganizationContext();
  const orgBase = selectedOrganization ? `/dashboard/${selectedOrganization.id}` : "/dashboard";
  const orgName = selectedOrganization?.name ?? "Organizations";
  const isPlatform = panel?.tone === "platform";

  return (
    <div className="flex min-h-full flex-col px-2.5 pb-3 pt-3">
      {panel ? (
        <>
          {/* Platform View keeps the switcher at its top, as the Organization view does;
              everything else is a level below the Organization and leads back up. */}
          {isPlatform ? (
            <div className="mb-2">
              <ContextSwitcher appearance="card" />
            </div>
          ) : (
            <BackLink
              href={panel.crumb?.href ?? orgBase}
              label={panel.crumb?.label ?? orgName}
            />
          )}
          {!isPlatform && (
            <div className="mb-1 rounded-xl p-2.5" style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}>
              <PanelHeader panel={{ ...panel, crumb: undefined }} flush />
            </div>
          )}
          <nav aria-label={panel.title} className="flex flex-1 flex-col">
            <PanelGroups panel={panel} surface="sidebar" />
            {panel.footer && (
              <div className="mt-1">
                <PanelLink item={panel.footer} tone={panel.tone} trailing surface="sidebar" />
              </div>
            )}
          </nav>
          {isPlatform && <BackLink href={orgBase} label={`Back to ${orgName}`} />}
        </>
      ) : (
        <>
          <div className="mb-2">
            <ContextSwitcher appearance="card" />
          </div>
          <nav aria-label="Organization" className="flex flex-col gap-px">
            {rail.items.map((item) => (
              <PanelLink key={item.key} item={item} tone="neutral" surface="sidebar" />
            ))}
          </nav>
          {/* useAgents is Organization-scoped, so it only mounts with one selected. */}
          {selectedOrganization && <SidebarAgents orgBase={orgBase} />}
          <div className="flex-1" />
        </>
      )}
      <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--line)" }}>
        <UserMenu appearance="row" />
      </div>
    </div>
  );
}

function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="mb-1.5 flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] hover:bg-[var(--bg-sunken)]"
      style={{ color: "var(--ink-3)" }}
    >
      <ChevronLeft size={15} aria-hidden />
      <span className="truncate">{label}</span>
    </Link>
  );
}

/** The team's Agents, pinned under the Organization's pages for quick switching. */
function SidebarAgents({ orgBase }: { orgBase: string }) {
  const { agents, isLoading } = useAgents();
  if (isLoading || agents.length === 0) return null;

  return (
    <div className="mt-2">
      <div
        className="flex items-center px-2.5 pb-1 pt-3.5 text-[10.5px] font-semibold uppercase tracking-[0.09em]"
        style={{ color: "var(--ink-4)" }}
      >
        <span className="flex-1">Agents</span>
        <span className="font-medium normal-case tracking-normal">{agents.length}</span>
      </div>
      <div className="flex flex-col gap-px">
        {agents.slice(0, SIDEBAR_AGENT_LIMIT).map((agent) => (
          <Link
            key={agent.id}
            href={`${orgBase}/agents/${agent.id}`}
            className="flex items-center gap-2.5 rounded-lg px-2.5 py-[6px] text-[13.5px] font-medium hover:bg-[var(--bg-sunken)]"
            style={{ color: "var(--ink-2)" }}
          >
            <AgentAvatar agent={agent} size="xs" />
            <span className="min-w-0 flex-1 truncate">{agent.name}</span>
            <span
              aria-label={agentStatusLabel(agent)}
              className="h-1.5 w-1.5 flex-shrink-0 rounded-full"
              style={{ background: agentStatusColor(agent) }}
            />
          </Link>
        ))}
        {agents.length > SIDEBAR_AGENT_LIMIT && (
          <Link
            href={orgBase}
            className="flex items-center gap-2 rounded-lg px-2.5 py-[6px] text-[13px] hover:bg-[var(--bg-sunken)]"
            style={{ color: "var(--ink-3)" }}
          >
            View all agents
            <ChevronRight size={13} aria-hidden className="ml-auto" />
          </Link>
        )}
      </div>
    </div>
  );
}

function agentStatusColor(agent: Agent) {
  if (agent.status === "ERROR") return "var(--err)";
  if (agent.status === "RUNNING") return "var(--ok)";
  return "var(--ink-5)";
}

function agentStatusLabel(agent: Agent) {
  if (agent.status === "ERROR") return "Needs attention";
  if (agent.status === "RUNNING") return "Running";
  return "Idle";
}
