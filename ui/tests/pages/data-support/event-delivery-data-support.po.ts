import { Page } from "@playwright/test";

export const ORG_A_ID = "22222222-2222-4222-8222-222222222222";

function zeroStats(overrides: Record<string, unknown> = {}) {
  return {
    count: 0,
    oldest_age_seconds: null,
    stale_threshold_seconds: 60,
    stale_count: 0,
    unknown_age_count: 0,
    ...overrides,
  };
}

export function emptySummary() {
  return {
    observed_at: "2026-07-31T12:00:00Z",
    total_count: 0,
    status_counts: { pending: 0, enqueued: 0, processing: 0, succeeded: 0, dead_lettered: 0 },
    pending: zeroStats(),
    enqueued: zeroStats(),
    processing: zeroStats(),
  };
}

export function delivery(overrides: Record<string, unknown> = {}) {
  return {
    id: "77777777-7777-4777-8777-777777777777",
    event_id: "88888888-8888-4888-8888-888888888888",
    event_name: "organization.role.changed",
    schema_version: 1,
    handler_name: "security_audit.projection",
    organization_id: ORG_A_ID,
    organization_name: "AAI Labs",
    status: "SUCCEEDED",
    attempt_count: 1,
    dead_letter_reason: null,
    last_error: null,
    created_at: "2026-07-31T11:00:00Z",
    enqueued_at: "2026-07-31T11:00:01Z",
    claimed_at: "2026-07-31T11:00:02Z",
    completed_at: "2026-07-31T11:00:03Z",
    status_since: "2026-07-31T11:00:03Z",
    observed_at: "2026-07-31T12:00:00Z",
    ...overrides,
  };
}

/**
 * Route mocks for the platform Event Delivery Monitor APIs (AF-247). Handlers guard on
 * HTTP method and fall back when it doesn't match, matching the sibling data-support
 * modules' registration-order convention.
 */
export class EventDeliveryDataSupport {
  constructor(private page: Page) {}

  async interceptSummary({
    summary,
    status = 200,
    detail = "Unable to load summary",
    delayMs = 0,
  }: {
    summary?: unknown;
    status?: number;
    detail?: string;
    delayMs?: number;
  } = {}) {
    await this.page.route("**/api/v1/platform/event-deliveries/summary", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (summary ?? emptySummary())),
      });
    });
  }

  async interceptEventTypes({ eventTypes }: { eventTypes?: unknown[] } = {}) {
    await this.page.route("**/api/v1/platform/event-deliveries/event-types", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          eventTypes ?? [{ event_name: "organization.role.changed", schema_versions: [1] }],
        ),
      });
    });
  }

  async interceptList({
    items,
    status = 200,
    detail = "Unable to load Event Deliveries",
    delayMs = 0,
  }: {
    items?: unknown[];
    status?: number;
    detail?: string;
    delayMs?: number;
  } = {}) {
    const list = items ?? [delivery()];
    await this.page.route("**/api/v1/platform/event-deliveries?*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail }
            : { page: 1, page_size: 50, total: list.length, items: list },
        ),
      });
    });
  }
}
