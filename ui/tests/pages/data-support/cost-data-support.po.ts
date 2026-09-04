import { Page } from "@playwright/test";

export const ORG_A_ID = "22222222-2222-4222-8222-222222222222";
export const ORG_B_ID = "33333333-3333-4333-8333-333333333333";
export const AGENT_A_ID = "44444444-4444-4444-8444-444444444444";
export const AGENT_B_ID = "55555555-5555-4555-8555-555555555555";

/** Fixtures use the wire shape (snake_case); the API client camelizes on the way in. */
export function costSummary(overrides: Record<string, unknown> = {}) {
  return {
    period: "THIRTY_DAYS",
    from_date: "2026-08-04T00:00:00Z",
    to_date: "2026-09-03T00:00:00Z",
    granularity: "day",
    total_spend: 143.03,
    total_calls: 4773,
    active_agents: 3,
    top_model: "openrouter/anthropic/claude-opus-5",
    top_model_spend: 64.55,
    avg_cost_per_call: 0.0299,
    avg_prompt_tokens: 12207,
    spend_over_time: [
      { bucket: "2026-08-04T00:00:00Z", spend: 4.87, calls: 62 },
      { bucket: "2026-08-05T00:00:00Z", spend: 9.55, calls: 101 },
      { bucket: "2026-08-06T00:00:00Z", spend: 10.66, calls: 118 },
    ],
    avg_prompt_tokens_over_time: [
      { bucket: "2026-08-04T00:00:00Z", avg_prompt_tokens: 11000 },
      { bucket: "2026-08-05T00:00:00Z", avg_prompt_tokens: 12500 },
      { bucket: "2026-08-06T00:00:00Z", avg_prompt_tokens: 13200 },
    ],
    spend_by_agent_over_time: [
      { bucket: "2026-08-04T00:00:00Z", agent_id: AGENT_A_ID, agent_name: "Aria", spend: 3.0 },
      { bucket: "2026-08-05T00:00:00Z", agent_id: AGENT_A_ID, agent_name: "Aria", spend: 5.5 },
      { bucket: "2026-08-04T00:00:00Z", agent_id: AGENT_B_ID, agent_name: "Meti", spend: 1.87 },
    ],
    cost_per_call_histogram: [
      { lower: 0, upper: 0.0001, calls: 1380 },
      { lower: 0.0001, upper: 0.001, calls: 350 },
      { lower: 0.001, upper: 0.005, calls: 811 },
      { lower: 1, upper: null, calls: 9 },
    ],
    ...overrides,
  };
}

export function platformCostSummary(overrides: Record<string, unknown> = {}) {
  return {
    ...costSummary(),
    daily_burn_rate: 4.77,
    credits_remaining: null,
    runway_days: null,
    unattributed_spend: 1.97,
    unattributed_calls: 49,
    organizations: [
      {
        organization_id: ORG_A_ID,
        organization_name: "AAI Labs",
        spend: 100.0,
        calls: 3000,
        agents: 2,
      },
      {
        organization_id: ORG_B_ID,
        organization_name: "Globex",
        spend: 41.06,
        calls: 1724,
        agents: 1,
      },
      {
        organization_id: null,
        organization_name: null,
        spend: 1.97,
        calls: 49,
        agents: 0,
      },
    ],
    ...overrides,
  };
}

export function costRecord(overrides: Record<string, unknown> = {}) {
  return {
    request_id: "gen-1788265277-4V4oZGda6TXwNP3zV0xw",
    occurred_at: "2026-09-01T12:21:16Z",
    spend: 0.0182,
    prompt_tokens: 1200,
    completion_tokens: 300,
    total_tokens: 1500,
    model: "openrouter/z-ai/glm-5.2",
    status: "success",
    request_duration_ms: 7805,
    agent_id: AGENT_A_ID,
    agent_name: "Aria",
    healed: false,
    ...overrides,
  };
}

export function platformCostRecord(overrides: Record<string, unknown> = {}) {
  return {
    ...costRecord(),
    organization_id: ORG_A_ID,
    organization_name: "AAI Labs",
    ...overrides,
  };
}

type ListOptions = {
  items?: unknown[];
  pages?: unknown[][];
  total?: number;
  status?: number;
  detail?: string;
};

/**
 * Route mocks for the org and platform cost APIs (AF-281).
 *
 * Handlers guard on HTTP method and fall back when it doesn't match, matching the
 * sibling data-support modules' registration-order convention.
 */
export class CostDataSupport {
  constructor(private page: Page) {}

  async interceptOrgSummary({
    summary,
    status = 200,
    detail = "Unable to load costs",
  }: { summary?: unknown; status?: number; detail?: string } = {}) {
    await this.page.route("**/organizations/*/costs/summary?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (summary ?? costSummary())),
      });
    });
  }

  async interceptOrgFilterOptions({
    agents,
    models,
  }: { agents?: unknown[]; models?: unknown[] } = {}) {
    await this.page.route("**/organizations/*/costs/filters/agents?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          agents ?? [
            { value: AGENT_A_ID, label: "Aria" },
            { value: AGENT_B_ID, label: "Meti" },
          ],
        ),
      });
    });
    await this.page.route("**/organizations/*/costs/filters/models?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          models ?? [
            { value: "openrouter/anthropic/claude-opus-5", label: "claude-opus-5" },
            { value: "openrouter/z-ai/glm-5.2", label: "glm-5.2" },
          ],
        ),
      });
    });
  }

  async interceptOrgList(options: ListOptions = {}) {
    await this.interceptList("**/organizations/*/costs?*", options, costRecord());
  }

  async interceptPlatformSummary({
    summary,
    status = 200,
    detail = "Unable to load costs",
  }: { summary?: unknown; status?: number; detail?: string } = {}) {
    await this.page.route("**/api/v1/platform/costs/summary?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (summary ?? platformCostSummary()),
        ),
      });
    });
  }

  async interceptPlatformOrganizations({
    organizations,
  }: { organizations?: unknown[] } = {}) {
    await this.page.route("**/api/v1/platform/costs/organizations?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          organizations ?? platformCostSummary().organizations,
        ),
      });
    });
  }

  /**
   * Agent and model options for the platform surface.
   *
   * `agentsByOrganization` keys the agent list by the organization_id on the
   * request, so a test can assert that choosing an organization narrows the list
   * rather than leaving it platform-wide.
   */
  async interceptPlatformFilterOptions({
    agents,
    agentsByOrganization,
    models,
  }: {
    agents?: unknown[];
    agentsByOrganization?: Record<string, unknown[]>;
    models?: unknown[];
  } = {}) {
    await this.page.route("**/api/v1/platform/costs/filters/agents?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const organizationId = new URL(route.request().url()).searchParams.get(
        "organization_id",
      );
      const scoped =
        organizationId && agentsByOrganization?.[organizationId]
          ? agentsByOrganization[organizationId]
          : (agents ?? [
              { value: AGENT_A_ID, label: "Aria in AAI Labs" },
              { value: AGENT_B_ID, label: "Meti in Globex" },
            ]);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scoped),
      });
    });
    await this.page.route("**/api/v1/platform/costs/filters/models?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          models ?? [
            { value: "openrouter/anthropic/claude-opus-5", label: "claude-opus-5" },
          ],
        ),
      });
    });
  }

  async interceptPlatformList(options: ListOptions = {}) {
    await this.interceptList("**/api/v1/platform/costs?*", options, platformCostRecord());
  }

  private async interceptList(
    pattern: string,
    { items, pages, total, status = 200, detail = "Unable to load costs" }: ListOptions,
    fallbackItem: unknown,
  ) {
    const pageList = pages ?? [items ?? [fallbackItem]];
    await this.page.route(pattern, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      if (status >= 400) {
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail }),
        });
        return;
      }
      const url = new URL(route.request().url());
      const page = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "50");
      const body = pageList[page - 1] ?? [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          page,
          page_size: pageSize,
          total: total ?? pageList.flat().length,
          items: body,
        }),
      });
    });
  }
}
