import { Page, Request } from "@playwright/test";

export const KPI_AGENT_A_ID = "44444444-4444-4444-8444-444444444444";
export const KPI_AGENT_B_ID = "55555555-5555-4555-8555-555555555555";

const VALUE_PATH = /\/api\/v1\/organizations\/[^/]+\/value(\?.*)?$/;
const ACTIVITY_PATH = /\/api\/v1\/organizations\/[^/]+\/value\/activity(\?.*)?$/;
const SETTINGS_PATH = /\/api\/v1\/organizations\/[^/]+\/value-settings$/;

const DEFAULT_MINUTES: [string, number][] = [
  ["PULL_REQUEST_OPENED", 20],
  ["DOCUMENT_AUTHORED", 20],
  ["COMMENT_POSTED", 5],
  ["MESSAGE_SENT", 5],
  ["MEETING_SCHEDULED", 5],
  ["SPREADSHEET_UPDATED", 5],
  ["FILE_UPLOADED", 2],
  ["RECORD_CREATED", 5],
  ["RECORD_UPDATED", 3],
  ["RECORD_DELETED", 1],
];

/** Mirrors the API catalogue order; MESSAGE_SENT carries an override of 8 minutes. */
export function valueSettings({
  hourlyRate = 60,
  overrides = { MESSAGE_SENT: 8 },
}: { hourlyRate?: number | null; overrides?: Record<string, number> } = {}) {
  return {
    hourly_rate_usd: hourlyRate,
    outcome_minutes: DEFAULT_MINUTES.map(([outcome_type, default_minutes]) => {
      const override = overrides[outcome_type] ?? null;
      return {
        outcome_type,
        default_minutes,
        override_minutes: override,
        effective_minutes: override ?? default_minutes,
        source: override === null ? "default" : "override",
      };
    }),
  };
}

/** Fixtures use the wire shape (snake_case); the API client camelizes on the way in. */
export function organizationValue(overrides: Record<string, unknown> = {}) {
  return {
    period: "THIRTY_DAYS",
    from_date: "2026-09-02T00:00:00Z",
    to_date: "2026-10-02T00:00:00Z",
    granularity: "day",
    totals: valueTotals(),
    series: [
      { bucket: "2026-09-30T00:00:00Z", minutes_saved: 60, value: 60, spend: 4.1 },
      { bucket: "2026-10-01T00:00:00Z", minutes_saved: 90, value: 90, spend: 8.3 },
    ],
    agents: [
      {
        agent_id: KPI_AGENT_A_ID,
        agent_name: "Aria",
        agent_deleted: false,
        successful_writes: 10,
        minutes_saved: 120,
        value: 120,
        spend: 9.4,
        value_to_spend_ratio: 12.765957,
      },
      {
        agent_id: KPI_AGENT_B_ID,
        agent_name: "Meti",
        agent_deleted: false,
        successful_writes: 2,
        minutes_saved: 30,
        value: 30,
        spend: 3.0,
        value_to_spend_ratio: 10,
      },
    ],
    top_outcome_types: [
      {
        outcome_type: "PULL_REQUEST_OPENED",
        successful_writes: 5,
        effective_minutes: 20,
        minutes_saved: 100,
        value: 100,
      },
      {
        outcome_type: "MESSAGE_SENT",
        successful_writes: 7,
        effective_minutes: 5,
        minutes_saved: 35,
        value: 35,
      },
    ],
    ...overrides,
  };
}

export function valueTotals(overrides: Record<string, unknown> = {}) {
  return {
    successful_writes: 12,
    minutes_saved: 150,
    value: 150,
    spend: 12.4,
    value_to_spend_ratio: 12.096774,
    unverified_writes: 3,
    failed_writes: 1,
    unclassified_actions: 2,
    hourly_rate_usd: 60,
    ...overrides,
  };
}

export function organizationActivity(overrides: Record<string, unknown> = {}) {
  return {
    period: "THIRTY_DAYS",
    from_date: "2026-09-02T00:00:00Z",
    to_date: "2026-10-02T00:00:00Z",
    granularity: "day",
    totals: activityTotals(),
    requests_series: [
      { bucket: "2026-09-30T00:00:00Z", requests: 200 },
      { bucket: "2026-10-01T00:00:00Z", requests: 280 },
    ],
    agents: [
      {
        ...activityTotals({ requests: 400, handled_coverage: 100, response_time_coverage: 80 }),
        agent_id: KPI_AGENT_A_ID,
        agent_name: "Aria",
        agent_deleted: false,
        spend: 9.4,
      },
      {
        ...activityTotals({ requests: 80, handled_coverage: 20, response_time_coverage: 18 }),
        agent_id: KPI_AGENT_B_ID,
        agent_name: "Meti",
        agent_deleted: false,
        spend: 3.0,
      },
    ],
    ...overrides,
  };
}

export function activityTotals(overrides: Record<string, unknown> = {}) {
  return {
    requests: 480,
    handled_without_failure_rate: 0.75,
    handled_coverage: 120,
    median_response_seconds: 1.462131,
    response_time_coverage: 98,
    cost_per_request: 0.0258,
    tool_calls_per_request: 1.4,
    ...overrides,
  };
}

export function valueAgent(overrides: Record<string, unknown> = {}) {
  return {
    agent_id: KPI_AGENT_A_ID,
    agent_name: "Aria",
    agent_deleted: false,
    successful_writes: 10,
    minutes_saved: 120,
    value: 120,
    spend: 9.4,
    value_to_spend_ratio: 12.765957,
    ...overrides,
  };
}

export function activityAgent(overrides: Record<string, unknown> = {}) {
  return {
    ...activityTotals(),
    agent_id: KPI_AGENT_A_ID,
    agent_name: "Aria",
    agent_deleted: false,
    spend: 9.4,
    ...overrides,
  };
}

type ReadOptions = { body?: unknown; status?: number; hold?: boolean };

export type ReadMock = {
  requests: URL[];
  respondWith: (options: ReadOptions) => void;
  release: () => void;
};

export class KpisDataSupport {
  constructor(private page: Page) {}

  async interceptValue(options: ReadOptions = {}): Promise<ReadMock> {
    return this.interceptRead(VALUE_PATH, organizationValue(), options);
  }

  async interceptActivity(options: ReadOptions = {}): Promise<ReadMock> {
    return this.interceptRead(ACTIVITY_PATH, organizationActivity(), options);
  }

  async interceptValueSettings(options: ReadOptions = {}): Promise<ReadMock> {
    return this.interceptRead(SETTINGS_PATH, valueSettings(), options);
  }

  private async interceptRead(
    path: RegExp,
    fallbackBody: unknown,
    initial: ReadOptions,
  ): Promise<ReadMock> {
    let current: ReadOptions = initial;
    const requests: URL[] = [];
    let release = () => {};
    const released = initial.hold
      ? new Promise<void>((resolve) => {
          release = resolve;
        })
      : Promise.resolve();
    await this.page.route(
      (url) => path.test(url.pathname + url.search),
      async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        requests.push(new URL(route.request().url()));
        await released;
        const status = current.status ?? 200;
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(
            status >= 400 ? { detail: "Unable to load" } : (current.body ?? fallbackBody),
          ),
        });
      },
    );
    return {
      requests,
      respondWith: (options) => {
        current = options;
      },
      release: () => release(),
    };
  }
}

export function isKpiRead(request: Request): boolean {
  const url = new URL(request.url());
  return VALUE_PATH.test(url.pathname) || ACTIVITY_PATH.test(url.pathname);
}
