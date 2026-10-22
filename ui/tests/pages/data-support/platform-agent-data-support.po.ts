import type { Page, Route } from "@playwright/test";

import { mockSize } from "./agent-size-data-support.po";

type Size = ReturnType<typeof mockSize>;

type PlatformAgent = {
  id: string;
  name: string;
  status: string;
  agent_type: string;
  created_at: string;
  organization_id: string;
  organization_name: string;
  agent_size_id: string | null;
  agent_size: Omit<Size, "enabled" | "sort_order" | "created_at" | "updated_at">;
  agent_size_set_by_platform: boolean;
  pending_size: boolean;
};

function option({
  id,
  name,
  cpu_request_millicores,
  cpu_limit_millicores,
  memory_request_bytes,
  memory_limit_bytes,
  is_default,
}: Size) {
  return { id, name, cpu_request_millicores, cpu_limit_millicores, memory_request_bytes, memory_limit_bytes, is_default };
}

export function mockPlatformAgent(overrides: Partial<PlatformAgent> = {}): PlatformAgent {
  return {
    id: "33333333-3333-4333-8333-000000000001",
    name: "Sally",
    status: "RUNNING",
    agent_type: "OPENCLAW",
    created_at: "2026-10-01T09:00:00Z",
    organization_id: "44444444-4444-4444-8444-000000000001",
    organization_name: "AAI Labs",
    agent_size_id: null,
    agent_size: option(mockSize()),
    agent_size_set_by_platform: false,
    pending_size: false,
    ...overrides,
  };
}

/**
 * The Platform Agents list and the size override, kept in memory the way the API keeps them:
 * the list filters by `search` and `organization_id`, and an override answers with the Agent
 * as saved. Returns what each request sent.
 */
export class PlatformAgentDataSupport {
  constructor(private page: Page) {}

  async intercept({ agents, sizes = [mockSize()] }: { agents: PlatformAgent[]; sizes?: Size[] }) {
    const stored = agents.map((agent) => ({ ...agent }));
    const listQueries: URLSearchParams[] = [];
    const writes: { agentId: string; body: { agent_size_id: string | null } }[] = [];

    const reply = (route: Route, status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    await this.page.route("**/api/v1/platform/agents?*", async (route) => {
      const params = new URL(route.request().url()).searchParams;
      listQueries.push(params);
      const search = params.get("search")?.toLowerCase() ?? "";
      const organizationId = params.get("organization_id");
      const items = stored.filter(
        (agent) =>
          (!organizationId || agent.organization_id === organizationId) &&
          (!search ||
            agent.name.toLowerCase().includes(search) ||
            agent.organization_name.toLowerCase().includes(search)),
      );
      return reply(route, 200, { page: 1, page_size: 50, total: items.length, items });
    });

    await this.page.route("**/api/v1/platform/agents/*/agent-size", async (route) => {
      const agentId = route.request().url().split("/").at(-2) ?? "";
      const body = route.request().postDataJSON() as { agent_size_id: string | null };
      writes.push({ agentId, body });
      const agent = stored.find((candidate) => candidate.id === agentId);
      if (!agent) return reply(route, 404, { detail: "Agent not found" });
      const size =
        sizes.find((candidate) => candidate.id === body.agent_size_id) ??
        sizes.find((candidate) => candidate.is_default) ??
        mockSize();
      Object.assign(agent, {
        agent_size_id: body.agent_size_id,
        agent_size: option(size),
        agent_size_set_by_platform: body.agent_size_id !== null,
        pending_size: agent.status === "RUNNING",
      });
      return reply(route, 200, agent);
    });

    return { listQueries, writes };
  }
}
