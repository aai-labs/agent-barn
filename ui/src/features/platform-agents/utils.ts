import type { PlatformAgent } from "./schemas";

export const PLATFORM_AGENTS_PAGE_SIZE = 50;

export const platformAgentsKey = {
  /** Platform data: no Organization's cache is its. */
  all: ["platform", "agents"] as const,
  list: (filters: { search: string; organizationId: string | null }) =>
    [...platformAgentsKey.all, "list", filters] as const,
};

export type OrganizationAgents = {
  organizationId: string;
  organizationName: string;
  agents: PlatformAgent[];
};

/**
 * The loaded Agents as one group per Organization. The API orders by Organization, so an
 * Organization split across two pages joins back into one group here.
 */
export function groupByOrganization(agents: PlatformAgent[]): OrganizationAgents[] {
  const groups = new Map<string, OrganizationAgents>();
  for (const agent of agents) {
    const group = groups.get(agent.organizationId);
    if (group) {
      group.agents.push(agent);
    } else {
      groups.set(agent.organizationId, {
        organizationId: agent.organizationId,
        organizationName: agent.organizationName,
        agents: [agent],
      });
    }
  }
  return [...groups.values()];
}
