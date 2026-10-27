import type { Page, Route } from "@playwright/test";

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;

export const STANDARD_SIZE_ID = "00000000-0000-7000-8000-00000000a51e";

type Size = {
  id: string;
  name: string;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_bytes: number;
  memory_limit_bytes: number;
  enabled: boolean;
  is_default: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
  agent_count: number;
  following_agent_count: number;
};

export function mockSize(overrides: Partial<Size> = {}): Size {
  return {
    id: STANDARD_SIZE_ID,
    name: "Standard",
    cpu_request_millicores: 50,
    cpu_limit_millicores: 500,
    memory_request_bytes: 320 * MIB,
    memory_limit_bytes: 1 * GIB,
    enabled: true,
    is_default: true,
    sort_order: 0,
    created_at: "2026-10-22T09:00:00Z",
    updated_at: "2026-10-22T09:00:00Z",
    agent_count: 0,
    following_agent_count: 0,
    ...overrides,
  };
}

/**
 * The Agent Size catalog, kept in memory the way the API keeps it: one default, made by
 * switching, never by clearing. Returns what each write sent.
 */
export class AgentSizeDataSupport {
  constructor(private page: Page) {}

  async intercept({
    sizes = [mockSize()],
    failWith,
  }: { sizes?: Size[]; failWith?: { status: number; detail: string } } = {}) {
    const catalog = sizes.map((size) => ({ ...size }));
    const writes: { method: string; id?: string; body?: Record<string, unknown> }[] = [];
    let created = 0;

    const reply = (route: Route, status: number, body?: unknown) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: body === undefined ? "" : JSON.stringify(body),
      });

    // By path, so the catalog read for one Organization (`?organization_id=`) is served too.
    await this.page.route((url) => url.pathname.endsWith("/api/v1/platform/agent-sizes"), async (route) => {
      const method = route.request().method();
      if (method === "GET") return reply(route, 200, catalog);
      const body = route.request().postDataJSON() as Record<string, unknown>;
      writes.push({ method, body });
      if (failWith) return reply(route, failWith.status, { detail: failWith.detail });
      created += 1;
      const size = mockSize({
        ...(body as Partial<Size>),
        id: `11111111-1111-4111-8111-${String(created).padStart(12, "0")}`,
        is_default: false,
        enabled: (body.enabled as boolean | undefined) ?? true,
      });
      catalog.push(size);
      return reply(route, 201, size);
    });

    await this.page.route("**/api/v1/platform/agent-sizes/*", async (route) => {
      const method = route.request().method();
      const id = route.request().url().split("/").pop() ?? "";
      const size = catalog.find((candidate) => candidate.id === id);
      const body = method === "PATCH" ? (route.request().postDataJSON() as Record<string, unknown>) : undefined;
      writes.push({ method, id, body });
      if (failWith) return reply(route, failWith.status, { detail: failWith.detail });
      if (!size) return reply(route, 404, { detail: "Agent size not found" });
      if (method === "DELETE") {
        catalog.splice(catalog.indexOf(size), 1);
        return reply(route, 204);
      }
      if (body?.is_default) catalog.forEach((candidate) => (candidate.is_default = false));
      Object.assign(size, body);
      return reply(route, 200, size);
    });

    return { writes, catalog };
  }

  /** What the active Organization may choose: the default first, then `allowed`. */
  async interceptOrganizationSizes({
    allowed = [],
    defaultSize = mockSize(),
  }: { allowed?: Size[]; defaultSize?: Size } = {}) {
    const option = ({ id, name, cpu_request_millicores, cpu_limit_millicores, memory_request_bytes, memory_limit_bytes, is_default }: Size) => ({
      id,
      name,
      cpu_request_millicores,
      cpu_limit_millicores,
      memory_request_bytes,
      memory_limit_bytes,
      is_default,
    });
    await this.page.route("**/api/v1/organizations/*/agent-sizes", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ can_choose: allowed.length > 0, sizes: [defaultSize, ...allowed].map(option) }),
      }),
    );
  }

  /** The platform setting an Organization's allowed set; answers with the Organization as saved. */
  async interceptSetOrganizationSizes(organization: Record<string, unknown>) {
    const writes: { agent_size_ids: string[] }[] = [];
    await this.page.route(`**/api/v1/platform/organizations/${organization.id}/agent-sizes`, async (route) => {
      const body = route.request().postDataJSON() as { agent_size_ids: string[] };
      writes.push(body);
      Object.assign(organization, { agent_size_ids: body.agent_size_ids });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(organization) });
    });
    return { writes };
  }

  /** Choosing an Agent's size: answers with the Agent on it, pending while it runs. */
  async interceptSetAgentSize(agent: Record<string, unknown>, sizes: Size[]) {
    const writes: { agent_size_id: string | null }[] = [];
    await this.page.route(`**/api/v1/organizations/*/agents/${agent.id}/agent-size`, async (route) => {
      const body = route.request().postDataJSON() as { agent_size_id: string | null };
      writes.push(body);
      const size = sizes.find((candidate) => candidate.id === body.agent_size_id) ?? sizes.find((s) => s.is_default);
      const updated = {
        ...agent,
        agent_size_id: body.agent_size_id,
        agent_size: size,
        pending_size: agent.status === "RUNNING",
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(updated) });
    });
    return { writes };
  }
}
