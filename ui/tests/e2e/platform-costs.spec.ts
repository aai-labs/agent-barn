import { expect, test } from "@playwright/test";

import {
  AGENT_A_ID,
  ORG_A_ID,
  platformCostRecord,
  platformCostSummary,
} from "../pages/data-support/cost-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const PLATFORM_COSTS_URL = "/dashboard/platform/costs";

test.describe("Platform costs (platform_admin)", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.costs.interceptPlatformFilterOptions();
    await data.costs.interceptPlatformOrganizations();
    await data.costs.interceptPlatformMonthly();
    await data.organizations.interceptListOrganizations({
      items: [
        {
          id: ORG_A_ID,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "AAI Labs",
        },
      ],
    });
  });

  test("renders platform-only figures alongside the shared ones", async ({ page }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    await expect(page.getByRole("heading", { name: "Platform Costs" })).toBeVisible();
    await expect(page.getByTestId("cost-total-spend")).toContainText("$143.03");
    await expect(page.getByTestId("cost-burn-rate")).toContainText("$4.77/day");
    await expect(page.getByTestId("cost-unattributed")).toContainText("$1.97");
    await expect(page.getByTestId("cost-unattributed")).toContainText("49 calls");
  });

  test("shows monthly spend across the platform, narrowed by the organization", async ({
    page,
  }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });
    const monthlyRequests: URLSearchParams[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/platform/costs/monthly")) {
        monthlyRequests.push(new URL(request.url()).searchParams);
      }
    });

    await page.goto(`${PLATFORM_COSTS_URL}?orgId=${ORG_A_ID}&orgName=AAI%20Labs`);

    await expect(page.getByTestId("monthly-costs-table").locator("tbody tr")).toHaveCount(3);
    await expect(page.getByTestId("monthly-previous")).toContainText("$20.00");
    await expect.poll(() => monthlyRequests.at(-1)?.get("organization_id")).toBe(ORG_A_ID);
  });

  test("credits show what is left of the key's limit", async ({ page }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    await expect(page.getByTestId("cost-credits")).toContainText("$250.00");
    await expect(page.getByTestId("cost-credits")).toContainText("of the key's $500.00 limit");
    await expect(page.getByTestId("cost-credits-warning")).toHaveCount(0);
  });

  test("a key with no limit is not reported as a missing balance", async ({ page }) => {
    await data.costs.interceptPlatformSummary({
      summary: platformCostSummary({
        credits_status: "no_limit",
        credits_remaining: null,
        credits_limit: null,
      }),
    });
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    await expect(page.getByTestId("cost-credits")).toContainText("No limit");
    await expect(page.getByTestId("cost-credits-warning")).toHaveCount(0);
  });

  test("an unreadable balance says so rather than looking healthy", async ({ page }) => {
    await data.costs.interceptPlatformSummary({
      summary: platformCostSummary({
        credits_status: "unavailable",
        credits_remaining: null,
        credits_limit: null,
      }),
    });
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    await expect(page.getByTestId("cost-credits")).toContainText("Unavailable");
    await expect(page.getByTestId("cost-credits-warning")).toContainText(
      "could not be read",
    );
  });

  test("a low balance warns before the credits run out", async ({ page }) => {
    await data.costs.interceptPlatformSummary({
      summary: platformCostSummary({
        credits_status: "ok",
        credits_remaining: 4.2,
        credits_limit: 500,
      }),
    });
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    const warning = page.getByTestId("cost-credits-warning");
    await expect(warning).toContainText("close to its spending limit");
    await expect(warning).toContainText("$4.20 left of the key's $500.00 limit");
    await expect(warning.getByRole("link", { name: /key settings/i })).toBeVisible();
  });

  test("an exhausted balance says agents have stopped", async ({ page }) => {
    await data.costs.interceptPlatformSummary({
      summary: platformCostSummary({
        credits_status: "ok",
        credits_remaining: 0,
        credits_limit: 500,
      }),
    });
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    const warning = page.getByTestId("cost-credits-warning");
    await expect(warning).toContainText("reached its spending limit");
    await expect(warning).toContainText("cannot make model calls");
    // The balance is the key's own cap, so account credit is not the remedy.
    await expect(warning).toContainText("adding credit to the account does not lift it");
    await expect(warning.getByRole("link", { name: /key settings/i })).toHaveAttribute(
      "href",
      "https://openrouter.ai/settings/keys",
    );
  });

  test("organizations are ranked, and the unattributed row is kept in the list", async ({
    page,
  }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);

    const rows = page.getByTestId("organization-spend-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toContainText("AAI Labs");
    await expect(rows.first()).toContainText("$100.00");
    // Kept in, or the rows would not add up to the total shown above them.
    await expect(rows.last()).toContainText("Unattributed");
  });

  test("choosing an organization scopes the agent filter to that organization", async ({
    page,
  }) => {
    await data.costs.interceptPlatformFilterOptions({
      agentsByOrganization: {
        [ORG_A_ID]: [{ value: AGENT_A_ID, label: "Aria in AAI Labs" }],
      },
    });
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);
    await expect(page.getByTestId("cost-list")).toBeVisible();

    // Before: every agent on the platform.
    await page.getByTestId("cost-agent-filter").click();
    await expect(page.getByRole("option", { name: "Meti in Globex" })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.getByTestId("organization-spend-row").first().click();
    await expect(page).toHaveURL(new RegExp(`orgId=${ORG_A_ID}`));

    // After: only that organization's agent.
    await page.getByTestId("cost-agent-filter").click();
    await expect(page.getByRole("option", { name: "Aria in AAI Labs" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Meti in Globex" })).toHaveCount(0);
  });

  test("agent options name their organization, so two Arias are distinguishable", async ({
    page,
  }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({ items: [platformCostRecord()], total: 1 });

    await page.goto(PLATFORM_COSTS_URL);
    await expect(page.getByTestId("cost-list")).toBeVisible();

    await page.getByTestId("cost-agent-filter").click();
    await expect(page.getByRole("option", { name: "Aria in AAI Labs" })).toBeVisible();
  });

  test("the rows table names each call's organization", async ({ page }) => {
    await data.costs.interceptPlatformSummary();
    await data.costs.interceptPlatformList({
      items: [platformCostRecord({ organization_name: "Globex" })],
      total: 1,
    });

    await page.goto(PLATFORM_COSTS_URL);

    await expect(page.getByTestId("cost-row")).toContainText("Globex");
  });
});
