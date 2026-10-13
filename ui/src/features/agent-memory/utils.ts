import type { Agent } from "@/features/agents/schemas";
import { agentsKey } from "@/features/agents/utils";
import { createQueryKeyStructure } from "@/shared/query-keys";

import type { MemoryGrant, MemoryItemType } from "./schemas";

export const MEMORY_ITEMS_PAGE_SIZE = 20;
export const MEMORY_AGENT_OPTIONS_PAGE_SIZE = 200;

const _organizationMemoryKeyBase = createQueryKeyStructure("organization-memory-items");
export const organizationMemoryKey = {
  ..._organizationMemoryKeyBase,
  items: (orgApiBase: string, params: { search: string; page: number }) =>
    [..._organizationMemoryKeyBase.all, orgApiBase, params] as const,
};

const _memoryGrantsKeyBase = createQueryKeyStructure("memory-grants");

// Keyed by the organization API base so one organization's grants are never served
// under another's key, on top of the organization-switch eviction of this family.
export const memoryGrantsKey = {
  ..._memoryGrantsKeyBase,
  forOrganization: (orgApiBase: string) => [..._memoryGrantsKeyBase.all, orgApiBase] as const,
};

export const agentMemoryKey = {
  items: (orgApiBase: string, agentId: string, params: { search: string; page: number }) =>
    [...agentsKey.detail(agentId), "memory-items", orgApiBase, params] as const,
  itemsFor: (agentId: string) => [...agentsKey.detail(agentId), "memory-items"] as const,
  agentOptions: (orgApiBase: string) =>
    agentsKey.list({ scope: { orgApiBase, purpose: "memory-grant-options" } }),
};

export const MEMORY_TYPE_LABEL: Record<MemoryItemType, string> = {
  world: "Fact",
  experience: "Experience",
  observation: "Observation",
};

export const ORGANIZATION_MEMORY_LABEL = "Organization Memory";

// Agent Memory's long-term layer is an opt-in add-on. The runtime's own notes are the
// built-in layer: always on, on the Agent's disk, and never shown by the viewer.
export const BUILT_IN_MEMORY_LABEL = "Built-in memory";
export const LONG_TERM_MEMORY_LABEL = "Long-term memory";

export function builtInMemoryDescription(agentType: Agent["agentType"]): string {
  return agentType === "hermes"
    ? "Hermes keeps its own notes (MEMORY.md, USER.md) on this Agent's disk and reads them at the start of every conversation."
    : "OpenClaw keeps its own memory notes on this Agent's disk and uses them in every conversation.";
}

export function grantSourceLabel(grant: Pick<MemoryGrant, "sourceAgentId" | "sourceAgentName">): string {
  return grant.sourceAgentId === null
    ? ORGANIZATION_MEMORY_LABEL
    : (grant.sourceAgentName ?? "Unknown Agent");
}
