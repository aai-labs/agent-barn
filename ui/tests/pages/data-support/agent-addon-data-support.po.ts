import type { Page, Route } from "@playwright/test";

import { MOCK_AGENT_ID } from "./agent-data-support.po";

type Kind = "pip" | "npm" | "git" | "binary" | "command";
type State = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "REVOKED";
type Spec = { version?: string | null; url?: string | null; commit?: string | null; sha256?: string | null; command?: string | null };
type Person = { full_name: string | null; email: string };

export type MockAgentAddon = {
  id: string;
  agent_id: string;
  kind: Kind;
  name: string;
  spec: Spec;
  reason: string;
  state: State;
  rejection_reason: string | null;
  requested_by: Person | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MockPlatformAgentAddon = Omit<MockAgentAddon, "requested_by"> & {
  organization_id: string;
  organization_name: string;
  agent_name: string;
  agent_type: string;
  agent_deleted: boolean;
  requested_by: Person | null;
  decided_by: Person | null;
};

export function mockAgentAddon(overrides: Partial<MockAgentAddon> = {}): MockAgentAddon {
  return {
    id: "55555555-5555-4555-8555-000000000001",
    agent_id: MOCK_AGENT_ID,
    kind: "pip",
    name: "humanize",
    spec: { version: "4.12.3" },
    reason: "Formats numbers and dates in reports.",
    state: "PENDING",
    rejection_reason: null,
    requested_by: { full_name: "Grace Hopper", email: "owner@example.com" },
    decided_at: null,
    created_at: "2026-10-21T09:00:00Z",
    updated_at: "2026-10-21T09:00:00Z",
    ...overrides,
  };
}

export function mockPlatformAgentAddon(overrides: Partial<MockPlatformAgentAddon> = {}): MockPlatformAgentAddon {
  return {
    ...mockAgentAddon(),
    organization_id: "44444444-4444-4444-8444-000000000001",
    organization_name: "Example Co",
    agent_name: "Assistant",
    agent_type: "hermes",
    agent_deleted: false,
    decided_by: null,
    ...overrides,
  };
}

const reply = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

/**
 * An Agent's add-ons and a Platform Administrator's requests list, kept in memory the way the
 * API keeps them. Returns what each request sent.
 */
export class AgentAddonDataSupport {
  constructor(private page: Page) {}

  async interceptAgentAddons({
    addons = [],
    availableKinds = ["pip", "npm", "git", "binary", "command"],
  }: { addons?: MockAgentAddon[]; availableKinds?: Kind[] } = {}) {
    const stored = addons.map((addon) => ({ ...addon }));
    const requests: Record<string, unknown>[] = [];
    const withdrawals: string[] = [];

    await this.page.route("**/agents/*/addons", async (route) => {
      if (route.request().method() === "GET") {
        return reply(route, 200, { items: stored, available_kinds: availableKinds, max_active: 20 });
      }
      const body = route.request().postDataJSON() as Record<string, string>;
      requests.push(body);
      const { kind, name, reason, ...spec } = body;
      const created = mockAgentAddon({
        id: `55555555-5555-4555-8555-${String(stored.length + 100).padStart(12, "0")}`,
        kind: kind as Kind,
        name,
        reason,
        spec,
        created_at: "2026-10-26T10:00:00Z",
      });
      stored.unshift(created);
      return reply(route, 201, created);
    });

    await this.page.route("**/agents/*/addons/*/withdraw", async (route) => {
      const addonId = route.request().url().split("/").at(-2) ?? "";
      withdrawals.push(addonId);
      const addon = stored.find((candidate) => candidate.id === addonId);
      if (!addon) return reply(route, 404, { detail: "Add-on not found" });
      Object.assign(addon, { state: "WITHDRAWN", decided_at: "2026-10-26T10:05:00Z" });
      return reply(route, 200, addon);
    });

    return { requests, withdrawals };
  }

  async interceptPlatformAddons({ requests }: { requests: MockPlatformAgentAddon[] }) {
    const stored = requests.map((request) => ({ ...request }));
    const listQueries: URLSearchParams[] = [];
    const decisions: { addonId: string; action: string; body: unknown }[] = [];

    await this.page.route("**/api/v1/platform/agent-addons?*", async (route) => {
      const params = new URL(route.request().url()).searchParams;
      listQueries.push(params);
      const state = params.get("state");
      const search = params.get("search")?.toLowerCase() ?? "";
      const items = stored.filter(
        (request) =>
          (!state || request.state === state) &&
          (!search ||
            [request.name, request.agent_name, request.organization_name].some((value) =>
              value.toLowerCase().includes(search),
            )),
      );
      return reply(route, 200, { page: 1, page_size: 50, total: items.length, items });
    });

    await this.page.route("**/api/v1/platform/agent-addons/*/*", async (route) => {
      const parts = route.request().url().split("/");
      const action = parts.at(-1) ?? "";
      const addonId = parts.at(-2) ?? "";
      const body = route.request().postData() ? route.request().postDataJSON() : null;
      decisions.push({ addonId, action, body });
      const request = stored.find((candidate) => candidate.id === addonId);
      if (!request) return reply(route, 404, { detail: "Add-on not found" });
      const state = { approve: "APPROVED", reject: "REJECTED", revoke: "REVOKED" }[action] as State;
      Object.assign(request, {
        state,
        rejection_reason: action === "reject" ? (body as { reason: string }).reason : null,
        decided_at: "2026-10-26T11:00:00Z",
        decided_by: { full_name: "Platform Admin", email: "admin@example.com" },
      });
      return reply(route, 200, request);
    });

    return { listQueries, decisions };
  }
}
