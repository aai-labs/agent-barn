"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import { ChatThreadList } from "@/features/agents/components/chat-tab";
import { ConversationChannelList } from "@/features/agents/components/conversations-tab";
import { StatusLine } from "@/features/agents/components/status-line";
import type { Agent } from "@/features/agents/schemas";

import { useCachedAgentHealth } from "../hooks/use-cached-agent";
import { useContextPanel, type ContextPanelModel } from "../hooks/use-context-panel";
import type { NavItem } from "../nav-model";

/**
 * The light panel beside the rail on desktop, below the path bar: the sections of the
 * thing the page belongs to. It is left out on pages that have no sections.
 */
export function ContextPanel() {
  const panel = useContextPanel();
  const pathname = usePathname() ?? "";
  // "Sections" from a chat list holds until you move to another section.
  const [sectionsShownOn, setSectionsShownOn] = useState<string | null>(null);
  if (!panel) return null;

  const activeKey = panel.groups.flatMap((group) => group.items).find((item) => item.active)?.key;
  // Chat and Conversations take the whole page, so their thread and channel lists take
  // the panel's place.
  const listTab =
    panel.agent && (activeKey === "chat" || activeKey === "conversations") ? activeKey : null;
  const routeKey = `${pathname}:${activeKey}`;
  const showList = listTab !== null && sectionsShownOn !== routeKey;

  return (
    <aside
      aria-label={`${panel.title} navigation`}
      className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-[248px] flex-shrink-0 flex-col overflow-y-auto px-3 pb-4 pt-4 lg:flex"
      style={{ background: "var(--bg-elev)", borderRight: "1px solid var(--line)" }}
    >
      {showList && panel.agent && listTab ? (
        <AgentListPanel
          agent={panel.agent}
          tab={listTab}
          onShowSections={() => setSectionsShownOn(routeKey)}
        />
      ) : (
        <>
          {panel.crumb && (
            <Link
              href={panel.crumb.href}
              className="af-hover-bg mb-1.5 inline-flex items-center gap-1 self-start rounded-md px-1.5 py-1 text-[12.5px]"
              style={{ color: "var(--ink-3)" }}
            >
              <ChevronLeft size={13} aria-hidden />
              {panel.crumb.label}
            </Link>
          )}
          {/* The path bar names the Agent and shows its avatar, status, runtime and model. */}
          <PanelHeader panel={panel} agentIdentity={false} />
          <nav aria-label={panel.title} className="flex flex-1 flex-col pt-1">
            <PanelGroups panel={panel} onNavigate={() => setSectionsShownOn(null)} />
          </nav>
          {panel.footer && (
            <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--line)" }}>
              <PanelLink item={panel.footer} trailing />
            </div>
          )}
        </>
      )}
    </aside>
  );
}

/**
 * The panel while Chat or Conversations fills the page: that section's threads or
 * channels, and the way back to the Agent's sections. The path bar names the Agent and
 * the section.
 */
function AgentListPanel({
  agent,
  tab,
  onShowSections,
}: {
  agent: Agent;
  tab: "chat" | "conversations";
  onShowSections: () => void;
}) {
  return (
    <>
      <button
        type="button"
        onClick={onShowSections}
        className="af-hover-bg mb-2 inline-flex items-center gap-1 self-start rounded-md px-1.5 py-1 text-[12.5px]"
        style={{ color: "var(--ink-3)" }}
      >
        <ChevronLeft size={13} aria-hidden />
        Sections
      </button>
      <div className="-mx-1.5 mt-1 flex min-h-0 flex-1 flex-col">
        {tab === "chat" ? (
          <ChatThreadList agentId={agent.id} />
        ) : (
          <div className="px-1.5">
            <ConversationChannelList agentId={agent.id} />
          </div>
        )}
      </div>
    </>
  );
}

export function PanelHeader({
  panel,
  agentIdentity = true,
}: {
  panel: ContextPanelModel;
  /**
   * False where the Agent is already named elsewhere on screen: the header then keeps
   * only a settings page's title, and an Agent's sections need none.
   */
  agentIdentity?: boolean;
}) {
  if (panel.agent && !agentIdentity) {
    return panel.subtitle ? (
      <div className="px-1.5 pb-1 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
        {panel.subtitle}
      </div>
    ) : null;
  }
  if (panel.agent) {
    return (
      <div className="px-1.5 pb-3" style={{ borderBottom: "1px solid var(--line)" }}>
        <AgentIdentity agent={panel.agent} subtitle={panel.subtitle} />
      </div>
    );
  }
  return (
    <div className="px-1.5 pb-2">
      <div className="text-[18px] font-semibold tracking-[-0.015em]" style={{ color: "var(--ink)" }}>
        {panel.title}
      </div>
      {panel.subtitle && (
        <div className="text-[12px] font-medium" style={{ color: "var(--ink-3)" }}>
          {panel.subtitle}
        </div>
      )}
    </div>
  );
}

function AgentIdentity({ agent, subtitle }: { agent: Agent; subtitle?: string }) {
  const health = useCachedAgentHealth(agent.id);
  return (
    <div className="flex items-center gap-2.5">
      <AgentAvatar agent={agent} size="md" />
      <div className="min-w-0">
        <div
          className="truncate text-[16px] font-semibold leading-tight tracking-[-0.01em]"
          style={{ color: "var(--ink)" }}
        >
          {agent.name}
        </div>
        <div className="mt-0.5">
          {subtitle ? (
            <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              {subtitle}
            </span>
          ) : (
            <StatusLine status={agent.status} health={health} />
          )}
        </div>
      </div>
    </div>
  );
}

export function PanelGroups({
  panel,
  onNavigate,
}: {
  panel: ContextPanelModel;
  onNavigate?: () => void;
}) {
  return (
    <>
      {panel.groups.map((group) => (
        <div key={group.key}>
          {group.label && (
            <div
              className="px-2.5 pb-1 pt-3.5 text-[10.5px] font-semibold uppercase tracking-[0.09em]"
              style={{ color: "var(--ink-4)" }}
            >
              {group.label}
            </div>
          )}
          <div className="flex flex-col gap-px pt-1">
            {group.items.map((item) => (
              <PanelLink key={item.key} item={item} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

export function PanelLink({
  item,
  trailing = false,
  onNavigate,
}: {
  item: NavItem;
  trailing?: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const danger = item.tone === "danger";
  const color = danger ? "var(--err)" : item.active ? "var(--ink)" : "var(--ink-2)";
  const iconColor = danger ? "var(--err)" : item.active ? "var(--ink)" : "var(--ink-3)";

  return (
    <>
      <Link
        href={item.href}
        aria-current={item.active ? "page" : undefined}
        onClick={onNavigate}
        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13.5px] transition-colors ${item.active ? "" : "af-hover-bg"}`}
        style={{
          color,
          fontWeight: item.active ? 600 : 500,
          background: item.active ? "var(--bg-soft)" : undefined,
        }}
      >
        <Icon size={16} aria-hidden style={{ color: iconColor, flexShrink: 0 }} />
        <span className="min-w-0 flex-1 truncate">{item.label}</span>
        {trailing && <ChevronRight size={14} aria-hidden style={{ color: "var(--ink-4)" }} />}
      </Link>
      {item.active && item.children && (
        <div className="my-1 ml-[19px] flex flex-col gap-px pl-2" style={{ borderLeft: "1px solid var(--line)" }}>
          {item.children.map((child) => (
            <PanelLink key={child.key} item={child} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </>
  );
}
