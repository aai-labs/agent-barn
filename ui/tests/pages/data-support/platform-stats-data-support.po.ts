import { Page } from "@playwright/test";

export const mockPlatformMessageStats = {
  observed_at: "2026-08-17T00:00:00Z",
  period: "THIRTY_DAYS",
  from_date: "2026-07-18T00:00:00Z",
  to_date: "2026-08-17T00:00:00Z",
  granularity: "day",
  inbound: 120,
  outbound: 80,
  total: 200,
  series: [
    { bucket: "2026-07-18T00:00:00Z", inbound: 10, outbound: 5 },
    { bucket: "2026-07-19T00:00:00Z", inbound: 20, outbound: 15 },
    { bucket: "2026-07-20T00:00:00Z", inbound: 90, outbound: 60 },
  ],
};

export const mockPlatformAgentStats = {
  observed_at: "2026-08-17T00:00:00Z",
  period: "THIRTY_DAYS",
  from_date: "2026-07-18T00:00:00Z",
  to_date: "2026-08-17T00:00:00Z",
  granularity: "day",
  total: 12,
  running: 8,
  stopped: 3,
  errored: 1,
  active: 7,
  series: [
    { bucket: "2026-07-18T00:00:00Z", existing: 10, created: 1, active: 4 },
    { bucket: "2026-07-19T00:00:00Z", existing: 11, created: 1, active: 5 },
    { bucket: "2026-07-20T00:00:00Z", existing: 12, created: 0, active: 7 },
  ],
};

export class PlatformStatsDataSupport {
  constructor(private page: Page) {}

  async interceptGetMessageStatsRequest({
    status = 200,
    detail = "Unable to load message stats",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/platform/stats/messages*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? mockPlatformMessageStats),
        ),
      });
    });
  }

  async interceptGetAgentStatsRequest({
    status = 200,
    detail = "Unable to load agent stats",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/platform/stats/agents*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (body ?? mockPlatformAgentStats),
        ),
      });
    });
  }
}
