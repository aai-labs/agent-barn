import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import { organizationLlmBudget } from "../pages/data-support/organization-data-support.po";
import userContext from "../fixtures/user-context.json";

const COSTS_URL = `/dashboard/${TEST_ORG_ID}/costs`;
const AGENTS_URL = `/dashboard/${TEST_ORG_ID}`;

function budget(state: string, spend: number | null, limit: number) {
  return organizationLlmBudget({ state, spend_usd: spend, limit_usd: limit, ceiling_usd: limit });
}

test.describe("Organization spend limit banner", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.costs.interceptOrgFilterOptions();
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [], total: 0 });
  });

  test("an approaching limit warns on the costs page", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: budget("warning", 40, 50),
    });
    await page.goto(COSTS_URL);

    await expect(
      page.getByText(/used \$40\.00 of \$50\.00 of its model spend limit this month/i),
    ).toBeVisible();
    // The cards cover a rolling range, not the allowance period — each has to say so
    // or the two totals read as contradicting each other.
    await expect(page.getByTestId("cost-total-spend")).toContainText(/last 30 days/i);
  });

  test("an exhausted limit is visible away from the costs page", async ({ page }) => {
    // Someone whose agent just stopped will not think to open Costs.
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: budget("exhausted", 50, 50),
    });
    await page.goto(AGENTS_URL);

    await expect(page.getByText(/agents can't make model calls until it renews/i)).toBeVisible();
    await expect(page.getByRole("link", { name: "Raise limit" })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=spend-limits`,
    );
  });

  test("a healthy limit shows nothing at all", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: budget("ok", 5, 50),
    });
    await page.goto(COSTS_URL);

    await expect(page.getByRole("status").filter({ hasText: /model spend limit/i })).toHaveCount(0);
  });

  test("an unobserved limit is not presented as safe or breached", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: budget("unknown", null, 50),
    });
    await page.goto(COSTS_URL);

    await expect(page.getByRole("status").filter({ hasText: /model spend limit/i })).toHaveCount(0);
  });

  test("a member sees no banner", async ({ page }) => {
    // The endpoint requires cost.read; the hook must not even ask.
    let asked = false;
    await page.route(`**/api/v1/organizations/${TEST_ORG_ID}/llm-budget`, async (route) => {
      asked = true;
      await route.fulfill({ status: 403, contentType: "application/json", body: "{}" });
    });
    await data.users.interceptGetUserContextRequest({
      userContext: {
        ...userContext,
        is_platform_admin: false,
        organization_users: userContext.organization_users.map((membership) => ({
          ...membership,
          role: "MEMBER",
        })),
      },
    });
    await page.goto(AGENTS_URL);

    await expect(page.getByRole("status").filter({ hasText: /model spend limit/i })).toHaveCount(0);
    expect(asked).toBe(false);
  });
});
