import { Page } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgentAllowedActions } from "./agent-data-support.po";

const HOUR_MS = 3_600_000;
const START = Date.parse("2026-09-28T12:00:00Z");

/** A day of hourly readings: memory climbing, CPU following it, one gap in the middle. */
export function usageSeries(points = 25) {
  return Array.from({ length: points }, (_, index) => ({
    bucket: new Date(START + index * HOUR_MS).toISOString(),
    memory_working_set_bytes: index === 12 ? null : 200_000_000 + index * 10_000_000,
    cpu_cores: index === 12 ? null : 0.02 + index * 0.001,
    cpu_throttled_ratio: index === 12 ? null : 0.01,
  }));
}

/** What the API returns for a running agent that reports usage. */
export function mockResourceUsage(overrides: Record<string, unknown> = {}) {
  return {
    agent_id: MOCK_AGENT_ID,
    range: "24h",
    from_date: "2026-09-28T12:00:00Z",
    to_date: "2026-09-29T12:00:00Z",
    step_seconds: 300,
    availability: "available",
    state: "reporting",
    observed_at: "2026-09-29T12:03:00Z",
    memory_working_set_bytes: 358_617_088,
    memory_limit_bytes: 1_073_741_824,
    memory_peak_bytes: 700_000_000,
    cpu_cores: 0.05,
    cpu_limit_cores: 0.5,
    cpu_average_cores: 0.04,
    cpu_throttled_ratio: 0.02,
    series: usageSeries(),
    ...overrides,
  };
}

/** The reading a row in the overview carries. */
export function mockUsageSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    state: "reporting",
    memory_working_set_bytes: 358_617_088,
    memory_limit_bytes: 1_073_741_824,
    cpu_cores: 0.05,
    cpu_limit_cores: 0.5,
    cpu_throttled_ratio: 0.02,
    ...overrides,
  };
}

export const MOCK_SECOND_AGENT_ID = "44444444-4444-4444-8444-444444444444";

export function mockOverviewItem(overrides: Record<string, unknown> = {}) {
  return {
    id: MOCK_AGENT_ID,
    name: "Maya",
    status: "RUNNING",
    agent_type: "openclaw",
    effective_model: "litellm/gpt-5-mini",
    created_at: "2026-03-14T00:00:00Z",
    allowed_actions: mockAgentAllowedActions,
    spend: { spend: 12.5, calls: 320, last_call_at: "2026-09-29T11:00:00Z" },
    resource_usage: mockUsageSnapshot(),
    ...overrides,
  };
}

export function mockAgentOverview(
  items: unknown[] = [mockOverviewItem()],
  overrides: Record<string, unknown> = {},
) {
  return {
    period: "THIRTY_DAYS",
    from_date: "2026-08-30T12:00:00Z",
    to_date: "2026-09-29T12:00:00Z",
    resource_usage_availability: "available",
    total: items.length,
    items,
    ...overrides,
  };
}

interface Options {
  body?: unknown;
  status?: number;
}

export class ResourceUsageDataSupport {
  constructor(private page: Page) {}

  /**
   * Answers one agent's resource usage. Returns the query strings it was asked with, so a
   * test can check the range the page sent. With no body it echoes the requested range,
   * the way the API does.
   */
  async interceptAgentResourceUsage(
    agentId: string = MOCK_AGENT_ID,
    { body, status = 200 }: Options = {},
  ): Promise<URLSearchParams[]> {
    const requests: URLSearchParams[] = [];
    await this.page.route(
      `**/api/v1/organizations/*/agents/${agentId}/resource-usage*`,
      async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        const params = new URL(route.request().url()).searchParams;
        requests.push(params);
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400
              ? { detail: "Unable to load resource usage" }
              : (body ?? mockResourceUsage({ agent_id: agentId, range: params.get("range") ?? "24h" })),
          ),
        });
      },
    );
    return requests;
  }

  /** Answers the agents overview. Returns the query strings it was asked with. */
  async interceptAgentOverview({ body, status = 200 }: Options = {}): Promise<URLSearchParams[]> {
    const requests: URLSearchParams[] = [];
    await this.page.route("**/api/v1/organizations/*/agent-overview*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      requests.push(new URL(route.request().url()).searchParams);
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail: "Unable to load the agents overview" } : (body ?? mockAgentOverview()),
        ),
      });
    });
    return requests;
  }
}
