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

export const PLATFORM_ACME_ID = "55555555-5555-4555-8555-555555555555";
export const PLATFORM_GLOBEX_ID = "66666666-6666-4666-8666-666666666666";
export const PLATFORM_ADA_ID = "77777777-7777-4777-8777-777777777777";
export const PLATFORM_CY_ID = "88888888-8888-4888-8888-888888888888";
/** A container that reports but that no live agent owns. */
export const PLATFORM_ORPHAN_ID = "99999999-9999-4999-8999-999999999999";

const GIB = 1024 ** 3;

export function mockPlatformAgent(overrides: Record<string, unknown> = {}) {
  return {
    agent_id: PLATFORM_ADA_ID,
    agent_name: "Ada",
    organization_id: PLATFORM_ACME_ID,
    organization_name: "Acme",
    memory_working_set_bytes: GIB,
    memory_limit_bytes: 2 * GIB,
    cpu_cores: 0.4,
    cpu_limit_cores: 1,
    cpu_throttled_ratio: 0.05,
    ...overrides,
  };
}

/**
 * The namespace's quota ceilings and what it commits. By default nothing is entered, and the
 * namespace commits 4 GiB and 1.5 cores of limits and 1 GiB and 0.5 cores of requests.
 */
export function mockCapacity(overrides: Record<string, unknown> = {}) {
  return {
    limits_memory_bytes: null,
    limits_cpu_cores: null,
    requests_memory_bytes: null,
    requests_cpu_cores: null,
    ceilings_updated_at: null,
    committed_limits_memory_bytes: 4 * GIB,
    committed_limits_cpu_cores: 1.5,
    committed_requests_memory_bytes: GIB,
    committed_requests_cpu_cores: 0.5,
    ...overrides,
  };
}

function platformTotals(overrides: Record<string, unknown> = {}) {
  return {
    agents_with_container: 2,
    agents_reporting: 3,
    memory_working_set_bytes: GIB + 1_950_000_000 + 268_435_456,
    memory_limit_bytes: 6 * GIB,
    cpu_cores: 0.55,
    cpu_limit_cores: 3,
    ...overrides,
  };
}

/**
 * Two organizations and one container nobody owns. Cy sits at 91% of its memory limit and
 * is throttled 30% of the last hour, so both warning cards have something to count.
 */
export function mockPlatformUsage(overrides: Record<string, unknown> = {}) {
  return {
    range: "24h",
    from_date: "2026-09-28T12:00:00Z",
    to_date: "2026-09-29T12:00:00Z",
    step_seconds: 300,
    observed_at: "2026-09-29T12:03:00Z",
    availability: "available",
    organization_id: null,
    totals: platformTotals(),
    capacity: mockCapacity(),
    organizations: [
      {
        organization_id: PLATFORM_GLOBEX_ID,
        organization_name: "Globex",
        agents_with_container: 1,
        agents_reporting: 1,
        memory_working_set_bytes: 1_950_000_000,
        memory_limit_bytes: 2 * GIB,
        cpu_cores: 0.1,
        cpu_limit_cores: 1,
      },
      {
        organization_id: PLATFORM_ACME_ID,
        organization_name: "Acme",
        agents_with_container: 1,
        agents_reporting: 1,
        memory_working_set_bytes: GIB,
        memory_limit_bytes: 2 * GIB,
        cpu_cores: 0.4,
        cpu_limit_cores: 1,
      },
      {
        organization_id: null,
        organization_name: null,
        agents_with_container: 0,
        agents_reporting: 1,
        memory_working_set_bytes: 268_435_456,
        memory_limit_bytes: 2 * GIB,
        cpu_cores: 0.05,
        cpu_limit_cores: 1,
      },
    ],
    agents: [
      mockPlatformAgent({
        agent_id: PLATFORM_CY_ID,
        agent_name: "Cy",
        organization_id: PLATFORM_GLOBEX_ID,
        organization_name: "Globex",
        memory_working_set_bytes: 1_950_000_000,
        cpu_cores: 0.1,
        cpu_throttled_ratio: 0.3,
      }),
      mockPlatformAgent(),
      mockPlatformAgent({
        agent_id: PLATFORM_ORPHAN_ID,
        agent_name: null,
        organization_id: null,
        organization_name: null,
        memory_working_set_bytes: 268_435_456,
        cpu_cores: 0.05,
        cpu_throttled_ratio: 0,
      }),
    ],
    series: usageSeries().map(({ bucket, memory_working_set_bytes, cpu_cores }) => ({
      bucket,
      memory_working_set_bytes,
      cpu_cores,
      cpu_throttled_ratio: null,
    })),
    ...overrides,
  };
}

/**
 * What an opened Heaviest agents row asks for. By default it is Cy, working, restarted three
 * times (the last one OOM-killed), at 91% of its memory limit and throttled 30% of the day.
 */
export function mockPlatformAgentDetails(overrides: Record<string, unknown> = {}) {
  return {
    agent_id: PLATFORM_CY_ID,
    name: "Cy",
    status: "RUNNING",
    agent_type: "hermes",
    effective_model: "litellm/gpt-5-mini",
    created_at: "2026-03-14T00:00:00Z",
    organization_id: PLATFORM_GLOBEX_ID,
    organization_name: "Globex",
    last_error_summary: null,
    health_status: "ok",
    restart_count: 3,
    termination_reason: "OOMKilled",
    resource_usage: {
      range: "24h",
      from_date: "2026-09-28T12:00:00Z",
      to_date: "2026-09-29T12:00:00Z",
      step_seconds: 300,
      availability: "available",
      state: "reporting",
      observed_at: "2026-09-29T12:03:00Z",
      memory_working_set_bytes: 1_950_000_000,
      memory_limit_bytes: 2 * GIB,
      memory_peak_bytes: 2_000_000_000,
      cpu_cores: 0.1,
      cpu_limit_cores: 1,
      cpu_average_cores: 0.08,
      cpu_throttled_ratio: 0.3,
      series: usageSeries(),
    },
    ...overrides,
  };
}

/** What the API returns when Prometheus cannot be read: only the database's count. */
export function mockPlatformUsageUnavailable(availability = "unavailable") {
  return mockPlatformUsage({
    availability,
    totals: {
      agents_with_container: 2,
      agents_reporting: null,
      memory_working_set_bytes: null,
      memory_limit_bytes: null,
      cpu_cores: null,
      cpu_limit_cores: null,
    },
    // The limits come from the database, so they are there; the committed figure is not.
    capacity: mockCapacity({ memory_committed_bytes: null, cpu_committed_cores: null }),
    organizations: [],
    agents: [],
    series: [],
  });
}

interface Options {
  body?: unknown;
  status?: number;
}

interface PlatformOptions {
  /** A fixed body, or one worked out from the query the page sent. */
  body?: Record<string, unknown> | ((params: URLSearchParams) => Record<string, unknown>);
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

  /** Answers the platform page. Returns the query strings it was asked with. */
  async interceptPlatformResourceUsage({
    body,
    status = 200,
  }: PlatformOptions = {}): Promise<URLSearchParams[]> {
    const requests: URLSearchParams[] = [];
    await this.page.route("**/api/v1/platform/resource-usage*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const params = new URL(route.request().url()).searchParams;
      requests.push(params);
      const answer =
        typeof body === "function"
          ? body(params)
          : (body ?? mockPlatformUsage({ range: params.get("range") ?? "24h" }));
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail: "Unable to load resource usage" } : answer),
      });
    });
    return requests;
  }

  /**
   * Answers the save of the capacity limits. Returns the bodies it was sent, as the API sees
   * them (snake_case). With no `body` it echoes them back as saved.
   */
  async interceptUpdateResourceLimits({
    status = 200,
    detail = "limits_memory_bytes must be greater than 0",
  }: { status?: number; detail?: string } = {}): Promise<Record<string, unknown>[]> {
    const sent: Record<string, unknown>[] = [];
    await this.page.route("**/api/v1/platform/resource-limits", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const body = route.request().postDataJSON() as Record<string, unknown>;
      sent.push(body);
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail }
            : {
                limits_memory_bytes: body.limits_memory_bytes ?? null,
                limits_cpu_cores: body.limits_cpu_cores ?? null,
                requests_memory_bytes: body.requests_memory_bytes ?? null,
                requests_cpu_cores: body.requests_cpu_cores ?? null,
                updated_at: "2026-10-01T12:00:00Z",
              },
        ),
      });
    });
    return sent;
  }

  /**
   * Answers an opened row. Returns the agent ids it was asked about. With no `body` every
   * agent gets the default details, under its own id.
   */
  async interceptPlatformAgentDetails({
    body,
    status = 200,
  }: {
    body?: (agentId: string) => Record<string, unknown>;
    status?: number;
  } = {}): Promise<string[]> {
    const asked: string[] = [];
    await this.page.route("**/api/v1/platform/resource-usage/agents/*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const agentId = new URL(route.request().url()).pathname.split("/").pop() ?? "";
      asked.push(agentId);
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail: "Unable to load this agent" }
            : (body?.(agentId) ?? mockPlatformAgentDetails({ agent_id: agentId })),
        ),
      });
    });
    return asked;
  }
}
