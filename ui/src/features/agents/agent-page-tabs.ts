import type { OrganizationRole } from "@/features/organizations/schemas";

import type { Agent } from "./schemas";
import { canAgent } from "./utils";

export type AgentPageTab =
  | "chat"
  | "conversations"
  | "tool-calls"
  | "logs"
  | "memory"
  | "files"
  | "workflows"
  | "playbooks"
  | "tasks"
  | "activity"
  | "costs"
  | "resource-usage"
  | "about";

export const AGENT_PAGE_TABS: AgentPageTab[] = [
  "chat",
  "conversations",
  "tool-calls",
  "logs",
  "memory",
  "files",
  "workflows",
  "playbooks",
  "tasks",
  "activity",
  "costs",
  "resource-usage",
  "about",
];

export const AGENT_PAGE_TAB_LABELS: Record<AgentPageTab, string> = {
  chat: "Chat",
  conversations: "Conversations",
  "tool-calls": "Tool calls",
  logs: "Logs",
  memory: "Memory",
  files: "Artifacts",
  workflows: "Workflows",
  playbooks: "Playbooks",
  tasks: "Tasks",
  activity: "Activity",
  costs: "Costs",
  "resource-usage": "Resource usage",
  about: "Overview",
};

/** Where an Agent opens: its Overview, listed first in the navigation panel. */
export const DEFAULT_AGENT_TAB: AgentPageTab = "about";

/**
 * The Agent page sections this viewer may open. Shared by the page and the navigation
 * panel, so both gate on the same Permissions.
 */
export function visibleAgentPageTabs(
  agent: Pick<Agent, "allowedActions"> | null | undefined,
  role: OrganizationRole | undefined,
  /** Whether the platform offers workflow authoring to this Agent (its workflow capabilities). */
  { workflowAuthoring = false }: { workflowAuthoring?: boolean } = {},
): AgentPageTab[] {
  const canReadActivity = canAgent(agent, "activity.read");
  const canReadCosts = canAgent(agent, "cost.read");
  // A run reads this Agent's activity and writes an Organization Skill, so it needs both
  // activity.read and the Owner/Admin Organization Role that holds skill.manage.
  const canExtractPlaybooks = canReadActivity && (role === "OWNER" || role === "ADMIN");
  return [
    // Memory content is conversation content, so it follows activity.read.
    ...(canReadActivity
      ? (["chat", "conversations", "tool-calls", "logs", "memory"] as AgentPageTab[])
      : []),
    // Workflows are part of the Agent itself, readable with agent.read, and only where the
    // platform offers authoring.
    ...(workflowAuthoring && canAgent(agent, "agent.read") ? (["workflows"] as AgentPageTab[]) : []),
    ...(canAgent(agent, "agent.read") ? (["files"] as AgentPageTab[]) : []),
    ...(canExtractPlaybooks ? (["playbooks"] as AgentPageTab[]) : []),
    ...(canAgent(agent, "task.read") ? (["tasks"] as AgentPageTab[]) : []),
    // Every part of Activity needs activity.read: the runtime diagnostics on
    // their own, the usage sections together with cost.read. The tab itself
    // decides what to show a reader who has only the first.
    ...(canReadActivity ? (["activity"] as AgentPageTab[]) : []),
    // Costs is gated on cost.read alone, independent of activity.read: a custom
    // Agent Access Role can grant one Permission without the other, and this is
    // the only tab that surfaces cost.read on its own — Activity's usage section
    // needs activity.read too.
    ...(canReadCosts ? (["costs"] as AgentPageTab[]) : []),
    // How the container is doing, so it follows Activity's gate rather than Costs':
    // the same activity.read that guards runtime diagnostics and health.
    ...(canReadActivity ? (["resource-usage"] as AgentPageTab[]) : []),
    "about",
  ];
}
