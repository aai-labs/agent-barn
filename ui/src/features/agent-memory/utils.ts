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

export function grantSourceLabel(grant: Pick<MemoryGrant, "sourceAgentId" | "sourceAgentName">): string {
  return grant.sourceAgentId === null
    ? ORGANIZATION_MEMORY_LABEL
    : (grant.sourceAgentName ?? "Unknown Agent");
}
