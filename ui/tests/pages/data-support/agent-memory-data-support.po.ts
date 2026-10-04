import type { Page, Route } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { MOCK_AGENT_ID, mockAgent } from "./agent-data-support.po";

export const MOCK_READER_AGENT_ID = "aaaaaaaa-0000-4000-8000-0000000000a1";
export const MOCK_SOURCE_AGENT_ID = "aaaaaaaa-0000-4000-8000-0000000000a2";
export const MOCK_GRANT_ID = "bbbbbbbb-0000-4000-8000-0000000000b1";

export const mockMemoryAgents = [
  { ...mockAgent, id: MOCK_READER_AGENT_ID, name: "Billing" },
  { ...mockAgent, id: MOCK_SOURCE_AGENT_ID, name: "Triage" },
];

export const mockMemoryGrant = {
  id: MOCK_GRANT_ID,
  agent_id: MOCK_READER_AGENT_ID,
  agent_name: "Billing",
  source_agent_id: MOCK_SOURCE_AGENT_ID,
  source_agent_name: "Triage",
  access: "read",
  created_at: "2026-10-01T09:00:00Z",
};

export const mockMemoryItems = [
  {
    id: "m-1",
    type: "world",
    text: "Customers prefer invoices in euros.",
    mentioned_at: "2026-10-01T12:30:00Z",
    shared: false,
  },
  {
    id: "m-2",
    type: "observation",
    text: "Quarterly reports are due on the first Monday.",
    mentioned_at: null,
    shared: true,
  },
  {
    id: "m-3",
    type: "experience",
    text: "<img src=x onerror=alert(1)> **not bold**",
    mentioned_at: "2026-09-30T08:00:00Z",
    shared: false,
  },
];

export type RecordedRequest = { method: string; url: URL; body: unknown };

export type MemoryGrantsMock = {
  requests: RecordedRequest[];
  grants: Record<string, unknown>[];
  /** Grants another admin created that GET does not list yet, so only the server knows of them. */
  unlisted: Record<string, unknown>[];
};
export type MemoryItemsMock = {
  requests: RecordedRequest[];
  /** Fail every following request with this status, or recover with `null`. */
  failWith: (status: number | null) => void;
};

function record(route: Route, into: RecordedRequest[]): RecordedRequest {
  const request = route.request();
  const entry = {
    method: request.method(),
    url: new URL(request.url()),
    body: request.postData() ? JSON.parse(request.postData() as string) : null,
  };
  into.push(entry);
  return entry;
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: status === 204 ? "" : JSON.stringify(body),
  });
}

/** Route mocks for the Agent Memory API. Stateful so a mutation is visible on the next read. */
export class AgentMemoryDataSupport {
  constructor(private page: Page) {}

  /** GET the Agent and PUT its memory setting, reflecting the saved value on later reads. */
  async interceptAgentMemorySetting({
    agent = mockAgent,
    enabled = false,
    putStatus = 200,
    putDetail = "Unable to change memory",
    startStatus = 200,
    stopStatus = 200,
  }: {
    agent?: Record<string, unknown>;
    enabled?: boolean;
    putStatus?: number;
    putDetail?: string;
    startStatus?: number;
    stopStatus?: number;
  } = {}) {
    const requests: RecordedRequest[] = [];
    let current = enabled;
    let status = agent.status;
    await this.page.route(`**/api/v1/organizations/*/agents/${agent.id}`, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return json(route, 200, { ...agent, status, memory_enabled: current });
    });
    await this.page.route(`**/api/v1/organizations/*/agents/${agent.id}/memory`, async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const entry = record(route, requests);
      if (putStatus >= 400) return json(route, putStatus, { detail: putDetail });
      current = (entry.body as { enabled: boolean }).enabled;
      return json(route, 200, { agent_id: agent.id, enabled: current });
    });
    for (const action of ["stop", "start"]) {
      await this.page.route(`**/api/v1/organizations/*/agents/${agent.id}/${action}`, async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        record(route, requests);
        const responseStatus = action === "stop" ? stopStatus : startStatus;
        if (responseStatus >= 400) return json(route, responseStatus, { detail: `Unable to ${action} Agent` });
        status = action === "stop" ? "STOPPED" : "RUNNING";
        return json(route, 200, { ...agent, status, memory_enabled: current });
      });
    }
    return { requests };
  }

  /** Organization Agent list used to populate grant choices. */
  async interceptAgentOptions({
    organizationId = TEST_ORG_ID,
    agents = mockMemoryAgents,
    status = 200,
  }: { organizationId?: string; agents?: unknown[]; status?: number } = {}) {
    await this.page.route(`**/api/v1/organizations/${organizationId}/agents?*`, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return json(
        route,
        status,
        status >= 400
          ? { detail: "Unable to load agents" }
          : { page: 1, page_size: 200, total: agents.length, items: agents },
      );
    });
  }

  async interceptMemoryGrants({
    organizationId = TEST_ORG_ID,
    grants = [],
    listStatus = 200,
  }: {
    organizationId?: string;
    grants?: Record<string, unknown>[];
    listStatus?: number;
  } = {}): Promise<MemoryGrantsMock> {
    const mock: MemoryGrantsMock = { requests: [], grants: [...grants], unlisted: [] };
    const names = new Map(
      mockMemoryAgents.map((agent) => [agent.id, agent.name] as [string, string]),
    );
    await this.page.route(
      `**/api/v1/organizations/${organizationId}/memory-grants**`,
      async (route) => {
        const entry = record(route, mock.requests);
        const method = entry.method;
        const idMatch = entry.url.pathname.match(/memory-grants\/([^/]+)$/);
        if (method === "GET") {
          return json(
            route,
            listStatus,
            listStatus >= 400 ? { detail: "Unable to load grants" } : mock.grants,
          );
        }
        if (method === "POST") {
          const { agent_id: agentId, source_agent_id: sourceId, access } = entry.body as {
            agent_id: string;
            source_agent_id: string | null;
            access: "read" | "write";
          };
          if (agentId === sourceId) {
            return json(route, 400, { detail: "An Agent already reads its own memories." });
          }
          if ([...mock.grants, ...mock.unlisted].some((g) => g.agent_id === agentId && g.source_agent_id === sourceId && g.access === access)) {
            return json(route, 409, { detail: "This Agent already has that memory grant." });
          }
          const created = {
            id: `bbbbbbbb-0000-4000-8000-${String(mock.grants.length + 2).padStart(12, "0")}`,
            agent_id: agentId,
            agent_name: names.get(agentId) ?? "Agent",
            source_agent_id: sourceId,
            access,
            source_agent_name: sourceId ? (names.get(sourceId) ?? "Agent") : null,
            created_at: "2026-10-02T10:00:00Z",
          };
          mock.grants.push(created);
          return json(route, 201, created);
        }
        if (method === "DELETE" && idMatch) {
          const index = mock.grants.findIndex((g) => g.id === idMatch[1]);
          if (index < 0) return json(route, 404, { detail: "Memory grant not found" });
          mock.grants.splice(index, 1);
          return json(route, 204, null);
        }
        return route.fallback();
      },
    );
    return mock;
  }

  /** GET the Agent's memory items, honouring `search`, `page`, and `page_size`. */
  async interceptMemoryItems({
    agentId = MOCK_AGENT_ID,
    organizationId = TEST_ORG_ID,
    items = mockMemoryItems,
  }: {
    agentId?: string;
    organizationId?: string;
    items?: Record<string, unknown>[];
  } = {}): Promise<MemoryItemsMock> {
    const requests: RecordedRequest[] = [];
    let failure: number | null = null;
    await this.page.route(
      `**/api/v1/organizations/${organizationId}/agents/${agentId}/memory/items*`,
      async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        const { url } = record(route, requests);
        if (failure) return json(route, failure, { detail: "Agent Memory is unavailable." });
        const search = (url.searchParams.get("search") ?? "").toLowerCase();
        const page = Number(url.searchParams.get("page") ?? "1");
        const pageSize = Number(url.searchParams.get("page_size") ?? "25");
        const matching = items.filter((item) => String(item.text).toLowerCase().includes(search));
        return json(route, 200, {
          page,
          page_size: pageSize,
          total: matching.length,
          items: matching.slice((page - 1) * pageSize, page * pageSize),
        });
      },
    );
    return {
      requests,
      failWith: (status) => {
        failure = status;
      },
    };
  }
}
