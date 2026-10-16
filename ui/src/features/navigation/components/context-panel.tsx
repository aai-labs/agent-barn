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
import { useNavVariant } from "../providers/nav-variant-provider";

/**
 * The light panel beside the rail on desktop: the sections of the thing the page
 * belongs to. It is titled with that thing's name so it never reads as a second copy
 * of the rail, and it is left out on pages that have no sections.
 */
export function ContextPanel({ belowTopBar = false }: { belowTopBar?: boolean }) {
  const panel = useContextPanel();
  const { variant } = useNavVariant();
  const pathname = usePathname() ?? "";
  // "Back to sections" from a chat list holds until you move to another section.
  const [sectionsShownOn, setSectionsShownOn] = useState<string | null>(null);
  if (!panel) return null;

  const activeKey = panel.groups.flatMap((group) => group.items).find((item) => item.active)?.key;
  // D2 gives Chat and Conversations the whole page, so their thread and channel lists
  // take the panel's place.
  const listTab =
    variant === "d2" && panel.agent && (activeKey === "chat" || activeKey === "conversations")
      ? activeKey
      : null;
  const routeKey = `${pathname}:${activeKey}`;
  const showList = listTab !== null && sectionsShownOn !== routeKey;

  return (
    <aside
      aria-label={`${panel.title} navigation`}
      className={`sticky hidden w-[248px] flex-shrink-0 flex-col overflow-y-auto px-3 pb-4 pt-4 lg:flex ${belowTopBar ? "top-14 h-[calc(100vh-3.5rem)]" : "top-0 h-screen"}`}
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
          {/* D2's top bar names the Agent and shows its avatar, status, runtime and model. */}
          <PanelHeader panel={panel} agentIdentity={variant !== "d2"} />
          <nav aria-label={panel.title} className="flex flex-1 flex-col pt-1">
            <PanelGroups panel={panel} onNavigate={() => setSectionsShownOn(null)} />
          </nav>
          {panel.footer && (
            <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--line)" }}>
              <PanelLink item={panel.footer} tone={panel.tone} trailing />
            </div>
          )}
        </>
      )}
    </aside>
  );
}

/**
 * The panel while Chat or Conversations fills the page: that section's threads or
 * channels, and the way back to the Agent's sections. Which Agent and section it is
 * shows in D2's top bar.
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
  flush = false,
  agentIdentity = true,
}: {
  panel: ContextPanelModel;
  /** Inside a card that already frames it, so no divider or padding of its own. */
  flush?: boolean;
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
      <div
        className={flush ? undefined : "px-1.5 pb-3"}
        style={flush ? undefined : { borderBottom: "1px solid var(--line)" }}
      >
        <AgentIdentity agent={panel.agent} subtitle={panel.subtitle} />
      </div>
    );
  }
  return (
    <div className={flush ? undefined : "px-1.5 pb-2"}>
      <div className="text-[18px] font-semibold tracking-[-0.015em]" style={{ color: "var(--ink)" }}>
        {panel.title}
      </div>
      {panel.subtitle && (
        <div
          className="text-[12px] font-medium"
          style={{ color: panel.tone === "platform" ? "var(--accent-color)" : "var(--ink-3)" }}
        >
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
        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
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

export type PanelSurface = "panel" | "sidebar";

export function PanelGroups({
  panel,
  onNavigate,
  surface = "panel",
}: {
  panel: ContextPanelModel;
  onNavigate?: () => void;
  surface?: PanelSurface;
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
              <PanelLink
                key={item.key}
                item={item}
                tone={panel.tone}
                onNavigate={onNavigate}
                surface={surface}
              />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

export function PanelLink({
  item,
  tone,
  trailing = false,
  onNavigate,
  surface = "panel",
}: {
  item: NavItem;
  tone: "neutral" | "platform";
  trailing?: boolean;
  onNavigate?: () => void;
  /** C's sidebar sits on the soft tone, so its active item is lifted onto white instead. */
  surface?: PanelSurface;
}) {
  const Icon = item.icon;
  const platform = tone === "platform";
  const color = item.tone === "danger" ? "var(--err)" : item.active ? (platform ? "var(--accent-ink)" : "var(--ink)") : "var(--ink-2)";
  const iconColor = item.tone === "danger" ? "var(--err)" : item.active ? (platform ? "var(--accent-color)" : "var(--ink)") : "var(--ink-3)";

  return (
    <>
      <Link
        href={item.href}
        aria-current={item.active ? "page" : undefined}
        onClick={onNavigate}
        className={`flex gap-2.5 rounded-lg px-2.5 text-[13.5px] transition-colors ${item.description ? "items-start py-2" : "items-center py-[7px]"} ${item.active ? "" : surface === "sidebar" ? "hover:bg-[var(--bg-sunken)]" : "af-hover-bg"}`}
        style={{
          color,
          fontWeight: item.active ? 600 : 500,
          background: item.active
            ? platform
              ? "var(--accent-soft)"
              : surface === "sidebar"
                ? "var(--bg-elev)"
                : "var(--bg-soft)"
            : undefined,
          boxShadow: item.active && surface === "sidebar" && !platform ? "var(--shadow-sm), 0 0 0 1px var(--line)" : undefined,
        }}
      >
        <Icon size={16} aria-hidden style={{ color: iconColor, marginTop: item.description ? 2 : 0, flexShrink: 0 }} />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{item.label}</span>
          {item.description && (
            <span className="block text-[12px] font-normal" style={{ color: "var(--ink-3)" }}>
              {item.description}
            </span>
          )}
        </span>
        {trailing && <ChevronRight size={14} aria-hidden style={{ color: "var(--ink-4)" }} />}
      </Link>
      {item.active && item.children && (
        <div className="my-1 ml-[19px] flex flex-col gap-px pl-2" style={{ borderLeft: "1px solid var(--line)" }}>
          {item.children.map((child) => (
            <PanelLink key={child.key} item={child} tone={tone} onNavigate={onNavigate} surface={surface} />
          ))}
        </div>
      )}
    </>
  );
}
