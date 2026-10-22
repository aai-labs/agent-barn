import {
  Activity,
  BookOpen,
  Bot,
  Brain,
  Building2,
  CreditCard,
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
  Workflow,
} from "lucide-react";

import type { AgentPageTab } from "@/features/agents/agent-page-tabs";
import type { AgentConfigurationSectionKey } from "@/features/agents/components/agent-configuration-utils";

export type NavItem = {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  active: boolean;
  tone?: "danger";
  /** Shown nested under the item while it is active, or always when `expanded`. */
  children?: NavItem[];
  expanded?: boolean;
  /** Called when someone points at, focuses or presses the item: a moment to fetch ahead. */
  onIntent?: () => void;
};

export type NavGroup = { key: string; label?: string; items: NavItem[] };

/** The Platform's tint, for its rail. */
export const PLATFORM_RAIL_BACKGROUND = "#1e1a4d";
export const RAIL_BACKGROUND = "#1a1815";

export const PLATFORM_BASE = "/dashboard/platform";

/** An Agent's page or one of its sub-pages: `/dashboard/{orgId}/agents/{agentId}[/{rest}]`. */
export type AgentRoute = { orgId: string; agentId: string; rest?: string };

const AGENT_ROUTE = /^\/dashboard\/([^/]+)\/agents\/([^/]+)(?:\/(.*))?$/;

export function parseAgentRoute(pathname: string): AgentRoute | null {
  const match = AGENT_ROUTE.exec(pathname);
  return match ? { orgId: match[1], agentId: match[2], rest: match[3] || undefined } : null;
}

type PlatformPage = {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
};

export type PlatformArea = {
  key: string;
  label: string;
  icon: LucideIcon;
  pages: PlatformPage[];
};

/**
 * Platform View's pages, grouped into the areas its rail lists; an area with more than
 * one page gets a panel listing them.
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
      },
    ],
  },
  {
    key: "users",
    label: "Users",
    icon: Users,
    pages: [
      {
        key: "users",
        label: "Users",
        href: `${PLATFORM_BASE}/users`,
        icon: Users,
      },
    ],
  },
  {
    key: "organizations",
    label: "Orgs",
    icon: Building2,
    pages: [
      {
        key: "organizations",
        label: "Organizations",
        href: `${PLATFORM_BASE}/organizations`,
        icon: Building2,
      },
    ],
  },
  {
    key: "agents",
    label: "Agents",
    icon: Bot,
    pages: [
      {
        key: "agents",
        label: "Agents",
        href: `${PLATFORM_BASE}/agents`,
        icon: Bot,
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
      },
      {
        key: "billing",
        label: "Billing",
        href: `${PLATFORM_BASE}/billing`,
        icon: CreditCard,
      },
      {
        key: "resources",
        label: "Resources",
        href: `${PLATFORM_BASE}/resource-usage`,
        icon: Cpu,
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
      },
      {
        key: "skills",
        label: "Skills",
        href: `${PLATFORM_BASE}/skills`,
        icon: Sparkles,
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
      },
      {
        key: "settings",
        label: "Settings",
        href: `${PLATFORM_BASE}/settings`,
        icon: Settings2,
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
  workflows: Workflow,
  playbooks: BookOpen,
  activity: Activity,
  costs: Wallet,
  "resource-usage": Cpu,
  about: LayoutDashboard,
};

export const AGENT_TAB_GROUPS: { key: string; label?: string; tabs: AgentPageTab[] }[] = [
  // The Overview (the About section) opens the Agent, so it leads the list.
  { key: "talk", tabs: ["about", "chat", "conversations", "memory"] },
  { key: "work", label: "Work", tabs: ["tool-calls", "logs", "workflows", "playbooks"] },
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
