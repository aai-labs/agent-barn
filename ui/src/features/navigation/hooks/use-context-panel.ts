"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Settings2 } from "lucide-react";

import {
  AGENT_PAGE_TAB_LABELS,
  DEFAULT_AGENT_TAB,
  visibleAgentPageTabs,
  type AgentPageTab,
} from "@/features/agents/agent-page-tabs";
import {
  AGENT_CONFIGURATION_ICONS,
  configurationSectionLabel,
  visibleAgentConfigurationSections,
} from "@/features/agents/components/agent-configuration-utils";
import type { Agent } from "@/features/agents/schemas";
import {
  ORGANIZATION_SETTINGS_ICONS,
  visibleOrganizationSettingsSections,
} from "@/features/organizations/components/organization-settings-utils";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import {
  PLATFORM_SETTINGS_SECTIONS,
  type PlatformSettingsSectionKey,
} from "@/features/platform-settings/components/platform-settings";

import {
  AGENT_CONFIGURATION_GROUPS,
  AGENT_TAB_GROUPS,
  AGENT_TAB_ICONS,
  PLATFORM_AREAS,
  PLATFORM_BASE,
  isPlatformPageActive,
  parseAgentRoute,
  type NavGroup,
  type NavItem,
} from "../nav-model";
import { useCachedAgent, useCachedWorkflowAuthoring } from "./use-cached-agent";

export type ContextPanelModel = {
  title: string;
  subtitle?: string;
  /** The way up a level, shown above the title. */
  crumb?: { label: string; href: string };
  /** Shown as the panel's header instead of the title when the panel is an Agent's. */
  agent?: Agent;
  groups: NavGroup[];
  footer?: NavItem;
};

/**
 * The navigation panel beside the rail: the sections of whatever the current page
 * belongs to (an Agent, its settings, the Organization's settings, Platform View).
 * Null where the page has no sections, so the panel is left out.
 */
export function useContextPanel(): ContextPanelModel | null {
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const { role, canManage, selectedOrganization } = useActiveOrgRole();
  const agentRoute = parseAgentRoute(pathname);
  const agent = useCachedAgent(agentRoute?.agentId);
  const workflowAuthoring = useCachedWorkflowAuthoring(agentRoute?.agentId);

  if (pathname.startsWith(PLATFORM_BASE)) {
    return platformPanel(pathname, searchParams.get("section"));
  }

  if (agentRoute) {
    const { orgId, agentId, rest } = agentRoute;
    const orgBase = `/dashboard/${orgId}`;
    const agentBase = `${orgBase}/agents/${agentId}`;

    if (rest === "configuration") {
      const sections = visibleAgentConfigurationSections(agent);
      const requested = searchParams.get("section");
      const activeKey = sections.some((section) => section.key === requested)
        ? requested
        : "profile";
      return {
        title: agent?.name ?? "Agent",
        subtitle: "Agent settings",
        crumb: { label: `Back to ${agent?.name ?? "Agent"}`, href: agentBase },
        agent,
        groups: agent
          ? AGENT_CONFIGURATION_GROUPS.map((group) => ({
              key: group.key,
              label: group.label,
              items: group.sections
                .filter((key) => sections.some((section) => section.key === key))
                .map((key) => ({
                  key,
                  label: configurationSectionLabel(key),
                  href: `${agentBase}/configuration?section=${key}`,
                  icon: AGENT_CONFIGURATION_ICONS[key],
                  active: key === activeKey,
                  tone: key === "danger" ? ("danger" as const) : undefined,
                })),
            })).filter((group) => group.items.length > 0)
          : [],
      };
    }

    const tabs = agent
      ? visibleAgentPageTabs(agent, role, { workflowAuthoring })
      : [];
    const requested = searchParams.get("tab") as AgentPageTab | null;
    // Only the Agent page itself has a selected section; its sub-pages (a connection,
    // a skill) are reached from settings and leave every section unselected.
    const activeTab = rest
      ? null
      : requested && tabs.includes(requested)
        ? requested
        : DEFAULT_AGENT_TAB;
    return {
      title: agent?.name ?? "Agent",
      crumb: { label: "Your team", href: orgBase },
      agent,
      groups: AGENT_TAB_GROUPS.map((group) => ({
        key: group.key,
        label: group.label,
        items: group.tabs
          .filter((tab) => tabs.includes(tab))
          .map((tab) => ({
            key: tab,
            label: AGENT_PAGE_TAB_LABELS[tab],
            href: tab === DEFAULT_AGENT_TAB ? agentBase : `${agentBase}?tab=${tab}`,
            icon: AGENT_TAB_ICONS[tab],
            active: tab === activeTab,
          })),
      })).filter((group) => group.items.length > 0),
      footer: agent
        ? {
            key: "agent-settings",
            label: "Agent settings",
            href: `${agentBase}/configuration`,
            icon: Settings2,
            active: rest === "configuration",
          }
        : undefined,
    };
  }

  const settingsMatch = /^\/dashboard\/([^/]+)\/settings(?:\/([^/]+))?/.exec(pathname);
  if (settingsMatch) {
    const [, orgId, subPage] = settingsMatch;
    const settingsBase = `/dashboard/${orgId}/settings`;
    const sections = visibleOrganizationSettingsSections(
      canManage,
      role === "OWNER" || role === "ADMIN",
    );
    const requested = subPage ?? searchParams.get("tab");
    const activeKey = sections.some((section) => section.key === requested)
      ? requested
      : sections[0]?.key;
    return {
      title: "Settings",
      subtitle: selectedOrganization?.name,
      groups: [
        {
          key: "sections",
          items: sections.map((section) => ({
            key: section.key,
            label: section.label,
            href: `${settingsBase}?tab=${section.key}`,
            icon: ORGANIZATION_SETTINGS_ICONS[section.key],
            active: section.key === activeKey,
          })),
        },
      ],
    };
  }

  return null;
}

function platformPanel(pathname: string, requestedSection: string | null): ContextPanelModel | null {
  const settingsSection: PlatformSettingsSectionKey =
    requestedSection && Object.hasOwn(PLATFORM_SETTINGS_SECTIONS, requestedSection)
      ? (requestedSection as PlatformSettingsSectionKey)
      : "agent-memory";
  const toItem = (page: (typeof PLATFORM_AREAS)[number]["pages"][number]): NavItem => {
    const active = isPlatformPageActive(pathname, page.href);
    return {
      key: page.key,
      label: page.label,
      href: page.href,
      icon: page.icon,
      active,
      // Platform settings' sections are listed whether or not you are on them, so each is
      // one click from anywhere in the area; one is selected only on the settings page.
      expanded: page.key === "settings",
      children:
        page.key === "settings"
          ? (Object.entries(PLATFORM_SETTINGS_SECTIONS) as [
              PlatformSettingsSectionKey,
              (typeof PLATFORM_SETTINGS_SECTIONS)[PlatformSettingsSectionKey],
            ][]).map(([key, section]) => ({
              key,
              label: section.label,
              href: `${page.href}?section=${key}`,
              icon: section.Icon,
              active: pathname === page.href && key === settingsSection,
            }))
          : undefined,
    };
  };

  // The rail picks the area, the panel lists that area's pages, styled like every other
  // panel. An area of one page needs no panel, as with the Organization's pages.
  const area = PLATFORM_AREAS.find((candidate) =>
    candidate.pages.some((page) => isPlatformPageActive(pathname, page.href)),
  );
  if (!area || area.pages.length < 2) return null;
  return {
    title: area.label,
    subtitle: "Platform",
    groups: [{ key: area.key, items: area.pages.map((page) => toItem(page)) }],
  };
}
