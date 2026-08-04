import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { delivery, emptySummary } from "../pages/data-support/event-delivery-data-support.po";

const MONITOR_URL = "/dashboard/platform/event-deliveries";

function summaryWithCounts() {
  return {
    ...emptySummary(),
    total_count: 2,
    status_counts: { pending: 0, enqueued: 0, processing: 0, succeeded: 1, dead_lettered: 1 },
  };
}

test.describe("Event Delivery Monitor (platform_admin)", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.eventDeliveries.interceptEventTypes();
    await data.organizations.interceptListOrganizations({
      items: [
        {
          id: "22222222-2222-4222-8222-222222222222",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "AAI Labs",
        },
        {
          id: "33333333-3333-4333-8333-333333333333",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "Globex",
        },
      ],
    });
  });

  test("renders the summary and the delivery list", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: summaryWithCounts() });
    await data.eventDeliveries.interceptList({ items: [delivery()] });

    await page.goto(MONITOR_URL);

    await expect(page.getByRole("heading", { name: "Event Delivery Monitor" })).toBeVisible();
    await expect(
      page.getByText("Inspect delivery pipeline health and diagnose handler failures."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /dead-lettered/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /organization\.role\.changed/i })).toBeVisible();
    await expect(page.getByText("AAI Labs")).toBeVisible();
  });

  test("renders platform deliveries without an organization", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: emptySummary() });
    await data.eventDeliveries.interceptList({
      items: [
        delivery({
          event_name: "platform.user_privilege.granted",
          organization_id: null,
          organization_name: null,
        }),
      ],
    });

    await page.goto(MONITOR_URL);

    const platformDelivery = page.getByRole("button", { name: /platform\.user_privilege\.granted/i });
    await expect(platformDelivery).toBeVisible();
    await expect(platformDelivery.getByText("Platform", { exact: true })).toBeVisible();

    await platformDelivery.click();
    await expect(page.getByText("Platform", { exact: true }).last()).toBeVisible();
  });

  test("shows loading skeletons before data resolves, then the real content", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: summaryWithCounts(), delayMs: 400 });
    await data.eventDeliveries.interceptList({ items: [delivery()], delayMs: 400 });

    await page.goto(MONITOR_URL);

    await expect(page.getByTestId("event-delivery-summary-skeleton")).toBeVisible();
    await expect(page.getByTestId("event-delivery-list-skeleton")).toBeVisible();

    await expect(page.getByRole("button", { name: /organization\.role\.changed/i })).toBeVisible();
    await expect(page.getByTestId("event-delivery-summary-skeleton")).not.toBeVisible();
    await expect(page.getByTestId("event-delivery-list-skeleton")).not.toBeVisible();
  });

  test("shows an error state with a retry action", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: emptySummary() });
    await data.eventDeliveries.interceptList({ status: 500, detail: "Unable to load Event Deliveries" });

    await page.goto(MONITOR_URL);

    await expect(page.getByText(/failed to load event deliveries/i)).toBeVisible();
    const retry = page.getByRole("button", { name: /try again/i });
    await expect(retry).toBeVisible();

    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/platform/event-deliveries?")),
      retry.click(),
    ]);
  });

  test("shows an empty state when there are no deliveries", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: emptySummary() });
    await data.eventDeliveries.interceptList({ items: [] });

    await page.goto(MONITOR_URL);

    await expect(page.getByText("No Event Deliveries yet")).toBeVisible();
  });

  test("expands one row's details at a time", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: summaryWithCounts() });
    await data.eventDeliveries.interceptList({
      items: [
        delivery({ id: "77777777-7777-4777-8777-777777777777", handler_name: "handler.one" }),
        delivery({
          id: "99999999-9999-4999-8999-999999999999",
          event_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          handler_name: "handler.two",
        }),
      ],
    });

    await page.goto(MONITOR_URL);

    await expect(page.getByText("handler.one")).toBeVisible();
    await page.getByText("handler.one").click();
    await expect(page.getByText("Delivery ID")).toBeVisible();

    await page.getByText("handler.two").click();
    await expect(page.getByText("Delivery ID")).toBeVisible();
    // Only one expanded panel should exist: the first delivery's detail (which shows its
    // own ID) must have collapsed when the second row opened.
    await expect(page.getByText("77777777-7777-4777-8777-777777777777")).not.toBeVisible();
  });

  test("refresh collapses the expanded row and re-fetches summary and deliveries", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: summaryWithCounts() });
    await data.eventDeliveries.interceptList({ items: [delivery()] });

    await page.goto(MONITOR_URL);

    await page.getByRole("button", { name: /organization\.role\.changed/i }).click();
    await expect(page.getByText("Delivery ID")).toBeVisible();

    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/platform/event-deliveries/summary")),
      page.waitForResponse((r) => r.url().includes("/api/v1/platform/event-deliveries?")),
      page.getByRole("button", { name: /refresh/i }).click(),
    ]);

    await expect(page.getByText("Delivery ID")).not.toBeVisible();
  });

  test("filters by organization via the searchable combobox", async ({ page }) => {
    await data.eventDeliveries.interceptSummary({ summary: summaryWithCounts() });
    await data.eventDeliveries.interceptList({ items: [delivery()] });

    await page.goto(MONITOR_URL);

    await page.getByRole("button", { name: /all organizations/i }).click();
    await page.getByPlaceholder(/search organizations/i).fill("Globex");
    await page.getByRole("option", { name: "Globex" }).click();

    await expect(page.getByRole("button", { name: "Globex" })).toBeVisible();
    await expect(page).toHaveURL(/orgId=33333333-3333-4333-8333-333333333333/);
    await expect(page).toHaveURL(/orgName=Globex/);
  });
});

test.describe("Event Delivery Monitor (non platform_admin)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is not accessible to a non platform_admin", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: { ...UserContext, is_platform_admin: false },
    });

    await page.goto(MONITOR_URL);

    await expect(page.getByText(/platform admin access required/i)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Event Delivery Monitor" })).not.toBeVisible();
  });
});
