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
    credits_status: "ok",
    credits_remaining: 250,
    credits_limit: 500,
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

/** Three months, oldest first, the last one in progress — the wire shape the
 *  monthly endpoints return. */
export function monthlyCosts() {
  return [
    {
      month: "2026-07-01T00:00:00Z",
      spend: 10,
      calls: 100,
      failed_calls: 2,
      prompt_tokens: 50000,
      completion_tokens: 10000,
      active_agents: 2,
      is_current: false,
      projected_spend: null,
    },
    {
      month: "2026-08-01T00:00:00Z",
      spend: 20,
      calls: 400,
      failed_calls: 5,
      prompt_tokens: 150000,
      completion_tokens: 30000,
      active_agents: 3,
      is_current: false,
      projected_spend: null,
    },
    {
      month: "2026-09-01T00:00:00Z",
      spend: 9,
      calls: 120,
      failed_calls: 1,
      prompt_tokens: 60000,
      completion_tokens: 12000,
      active_agents: 3,
      is_current: true,
      projected_spend: 30,
    },
  ];
}

export function agentCost(overrides: Record<string, unknown> = {}) {
  return {
    agent_id: AGENT_A_ID,
    agent_name: "Maya",
    model: "openrouter/z-ai/glm-5.2",
    status: "active",
    period: "THIRTY_DAYS",
    from_date: "2026-08-01T00:00:00Z",
    to_date: "2026-08-31T00:00:00Z",
    granularity: "day",
    total_cost: 12.5,
    total_tokens: 3000,
    prompt_tokens: 2000,
    completion_tokens: 1000,
    total_calls: 8,
    failed_calls: 2,
    healed_calls: 0,
    avg_cost_per_call: 1.5625,
    avg_prompt_tokens: 250,
    avg_duration_ms: 1840,
    daily_burn_rate: 0.42,
    first_call_at: "2026-08-01T09:00:00Z",
    last_call_at: "2026-08-02T17:00:00Z",
    models_breakdown: [
      {
        model: "litellm/openrouter/z-ai/glm-5.2",
        total_cost: 9.0,
        prompt_tokens: 1500,
        completion_tokens: 700,
        calls: 6,
      },
      {
        model: "litellm/openrouter/openai/gpt-5-mini",
        total_cost: 3.5,
        prompt_tokens: 500,
        completion_tokens: 300,
        calls: 2,
      },
    ],
    spend_over_time: [
      { bucket: "2026-08-01T00:00:00Z", spend: 4.5, calls: 3 },
      { bucket: "2026-08-02T00:00:00Z", spend: 8.0, calls: 5 },
    ],
    avg_prompt_tokens_over_time: [
      { bucket: "2026-08-01T00:00:00Z", avg_prompt_tokens: 240 },
      { bucket: "2026-08-02T00:00:00Z", avg_prompt_tokens: 260 },
    ],
    cost_per_call_histogram: [
      { lower: 0, upper: 0.0001, calls: 2 },
      { lower: 1, upper: null, calls: 6 },
    ],
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

  async interceptOrgMonthly({ months, status = 200 }: { months?: unknown[]; status?: number } = {}) {
    await this.interceptJson("**/organizations/*/costs/monthly?*", months ?? monthlyCosts(), status);
  }

  async interceptPlatformMonthly({ months, status = 200 }: { months?: unknown[]; status?: number } = {}) {
    await this.interceptJson("**/api/v1/platform/costs/monthly?*", months ?? monthlyCosts(), status);
  }

  /**
   * Every read the Agent's Costs tab makes. Each piece can be overridden, and the
   * handlers record the query string of every summary request so a test can
   * assert what the tab asked for.
   */
  async interceptAgentCosts(
    agentId: string,
    {
      summary,
      summaryStatus = 200,
      calls = {},
      months,
      models,
    }: {
      summary?: unknown;
      summaryStatus?: number;
      calls?: ListOptions;
      months?: unknown[];
      models?: unknown[];
    } = {},
  ): Promise<URLSearchParams[]> {
    const summaryRequests: URLSearchParams[] = [];
    await this.page.route(`**/costs/agents/${agentId}*`, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      summaryRequests.push(new URL(route.request().url()).searchParams);
      await route.fulfill({
        status: summaryStatus,
        contentType: "application/json",
        body: JSON.stringify(
          summaryStatus >= 400 ? { detail: "Unable to load costs" } : (summary ?? agentCost()),
        ),
      });
    });
    await this.interceptList(`**/costs/agents/${agentId}/calls?*`, calls, costRecord());
    await this.interceptJson(
      `**/costs/agents/${agentId}/monthly?*`,
      months ?? monthlyCosts(),
      summaryStatus,
    );
    await this.interceptJson(
      `**/costs/agents/${agentId}/filters/models*`,
      models ?? [
        { value: "litellm/openrouter/z-ai/glm-5.2", label: "glm-5.2" },
        { value: "litellm/openrouter/openai/gpt-5-mini", label: "gpt-5-mini" },
      ],
      summaryStatus,
    );
    return summaryRequests;
  }

  private async interceptJson(pattern: string, body: unknown, status: number) {
    await this.page.route(pattern, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail: "Unable to load costs" } : body),
      });
    });
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
