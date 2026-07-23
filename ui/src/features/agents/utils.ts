import { createQueryKeyStructure } from "@/shared/query-keys";

import type { Agent, AgentPermissionKey } from "./schemas";

export const AGENTS_PAGE_SIZE = 50;
export const TEMPLATES_PAGE_SIZE = 50;
export const CONVERSATION_MESSAGES_PAGE_SIZE = 6;
export const TOOL_CALLS_PAGE_SIZE = 20;
const _agentsKeyBase = createQueryKeyStructure("agents");

export const templatesKey = createQueryKeyStructure("templates");

export type ConversationsFiltersKey = {
  fromDate: string;
  toDate: string;
};

export const agentsKey = {
  ..._agentsKeyBase,
  health: (id: string) => [..._agentsKeyBase.detail(id), "health"] as const,
  shareSettings: (id: string) => [..._agentsKeyBase.detail(id), "share"] as const,
  shareRoles: () => [..._agentsKeyBase.all, "share-roles"] as const,
  conversationChannels: (agentId: string) =>
    [..._agentsKeyBase.detail(agentId), "conversation-channels"] as const,
  conversationMessages: (
    agentId: string,
    channelId: string,
    filters: ConversationsFiltersKey,
  ) =>
    [
      ..._agentsKeyBase.detail(agentId),
      "conversation-messages",
      channelId,
      filters,
    ] as const,
  logs: (id: string) => [..._agentsKeyBase.detail(id), "logs"] as const,
  slackChannels: (id: string) => [..._agentsKeyBase.detail(id), "slack-channels"] as const,
  slackUsers: (id: string) => [..._agentsKeyBase.detail(id), "slack-users"] as const,
  models: () => [..._agentsKeyBase.all, "models"] as const,
};

export const toolCallsKey = createQueryKeyStructure("tool-calls");

const AGENT_COLORS = [
  ["#4f46e5", "#7c3aed"],
  ["#0d9488", "#15803d"],
  ["#b45309", "#c2410c"],
  ["#be185d", "#9d174d"],
  ["#0e6fd4", "#0369a1"],
  ["#7c2d12", "#9a3412"],
  ["#4338ca", "#5b21b6"],
  ["#0f766e", "#0e7490"],
];

export function canAgent(
  agent: Pick<Agent, "allowedActions"> | null | undefined,
  permission: AgentPermissionKey,
): boolean {
  return agent?.allowedActions.includes(permission) ?? false;
}

export function agentColor(id: string): string {
  const seed = parseInt(id.replace(/-/g, "")[0], 16);
  const c = AGENT_COLORS[seed % AGENT_COLORS.length];
  return `linear-gradient(135deg, ${c[0]} 0%, ${c[1]} 100%)`;
}

export function agentInitials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

const MODEL_DISPLAY_PREFIX = "litellm/openrouter/";

// Strips the internal litellm/openrouter routing prefix for display, leaving the
// provider/model slug (e.g. "openai/gpt-5-mini"). No-op if the prefix is absent.
export function formatModelName(model: string): string {
  return model.startsWith(MODEL_DISPLAY_PREFIX)
    ? model.slice(MODEL_DISPLAY_PREFIX.length)
    : model;
}
