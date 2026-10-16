import {
  Activity,
  BookOpen,
  Brain,
  Building2,
  Cpu,
  FileText,
  LayoutDashboard,
  Layers,
  LayoutGrid,
  MessageSquare,
  MessagesSquare,
  Receipt,
  Send,
  Server,
  Settings2,
  Sparkles,
  SquareTerminal,
  Users,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { AgentPageTab } from "@/features/agents/agent-page-tabs";
import type { AgentConfigurationSectionKey } from "@/features/agents/components/agent-configuration-utils";

export type NavItem = {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  active: boolean;
  /** A second line under the label, used where a panel lists only a few pages. */
  description?: string;
  tone?: "danger";
  /** Shown nested under the item while it is active. */
  children?: NavItem[];
};

export type NavGroup = { key: string; label?: string; items: NavItem[] };

/** The Platform's tint: the D2 rail and every active Platform panel item use it. */
export const PLATFORM_RAIL_BACKGROUND = "#1e1a4d";
export const RAIL_BACKGROUND = "#1a1815";

export const PLATFORM_BASE = "/dashboard/platform";

type PlatformPage = {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
};

export type PlatformArea = {
  key: string;
  label: string;
  icon: LucideIcon;
  /** The heading D's panel lists the area under, when it differs from the area's label. */
  group?: string;
  pages: PlatformPage[];
};

/**
 * Platform View's pages, grouped into the areas that D2 puts on its rail; an area with
 * more than one page gets a panel listing them. D lists the same pages in its panel,
 * under each area's group.
 */
export const PLATFORM_AREAS: PlatformArea[] = [
  {
    key: "overview",
    label: "Overview",
    icon: LayoutGrid,
    pages: [
      {
        key: "overview",
        label: "Overview",
        href: PLATFORM_BASE,
        icon: LayoutGrid,
        description: "Every organization at a glance",
      },
    ],
  },
  {
    key: "users",
    label: "Users",
    icon: Users,
    group: "People",
    pages: [
      {
        key: "users",
        label: "Users",
        href: `${PLATFORM_BASE}/users`,
        icon: Users,
        description: "Everyone with a login",
      },
    ],
  },
  {
    key: "organizations",
    label: "Orgs",
    icon: Building2,
    group: "People",
    pages: [
      {
        key: "organizations",
        label: "Organizations",
        href: `${PLATFORM_BASE}/organizations`,
        icon: Building2,
        description: "Customers and trials",
      },
    ],
  },
  {
    key: "spend",
    label: "Spend",
    icon: Wallet,
    pages: [
      {
        key: "costs",
        label: "Costs",
        href: `${PLATFORM_BASE}/costs`,
        icon: Receipt,
        description: "LLM spend by organization",
      },
      {
        key: "resources",
        label: "Resources",
        href: `${PLATFORM_BASE}/resource-usage`,
        icon: Cpu,
        description: "CPU, memory and capacity",
      },
    ],
  },
  {
    key: "catalog",
    label: "Catalog",
    icon: Layers,
    pages: [
      {
        key: "templates",
        label: "Templates",
        href: `${PLATFORM_BASE}/templates`,
        icon: FileText,
        description: "Agent definitions for every organization",
      },
      {
        key: "skills",
        label: "Skills",
        href: `${PLATFORM_BASE}/skills`,
        icon: Sparkles,
        description: "Tools shared with every organization",
      },
    ],
  },
  {
    key: "system",
    label: "System",
    icon: Server,
    pages: [
      {
        key: "event-deliveries",
        label: "Event deliveries",
        href: `${PLATFORM_BASE}/event-deliveries`,
        icon: Send,
        description: "Domain Events and their handlers",
      },
      {
        key: "settings",
        label: "Settings",
        href: `${PLATFORM_BASE}/settings`,
        icon: Settings2,
        description: "Memory, Playbooks and Trials",
      },
    ],
  },
];

/** Overview is the prefix of every other Platform page, so it matches exactly. */
export function isPlatformPageActive(pathname: string, href: string) {
  return href === PLATFORM_BASE ? pathname === PLATFORM_BASE : pathname.startsWith(href);
}

export const AGENT_TAB_ICONS: Record<AgentPageTab, LucideIcon> = {
  chat: MessageSquare,
  conversations: MessagesSquare,
  "tool-calls": Wrench,
  logs: SquareTerminal,
  memory: Brain,
  playbooks: BookOpen,
  activity: Activity,
  costs: Wallet,
  "resource-usage": Cpu,
  about: LayoutDashboard,
};

export const AGENT_TAB_GROUPS: { key: string; label?: string; tabs: AgentPageTab[] }[] = [
  // The Overview (the About section) opens the Agent, so it leads the list.
  { key: "talk", tabs: ["about", "chat", "conversations", "memory"] },
  { key: "work", label: "Work", tabs: ["tool-calls", "logs", "playbooks"] },
  { key: "health", label: "Health", tabs: ["activity", "costs", "resource-usage"] },
];

export const AGENT_CONFIGURATION_GROUPS: {
  key: string;
  label: string;
  sections: AgentConfigurationSectionKey[];
}[] = [
  { key: "identity", label: "Identity", sections: ["profile", "template"] },
  { key: "connections", label: "Connections", sections: ["channels", "webhooks", "keys"] },
  { key: "behaviour", label: "Behaviour", sections: ["skills", "memory", "override"] },
  { key: "safety", label: "Safety", sections: ["restore", "spend", "danger"] },
];
