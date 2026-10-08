import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { ORG_A_ID } from "../pages/data-support/organization-data-support.po";

const DETAIL_URL = `/dashboard/platform/organizations/${ORG_A_ID}`;

function organization(budget: { usd: number; duration: string; own?: number | null }) {
  return {
    id: ORG_A_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    owner_email: "owner@example.com",
    owner_name: "Grace Hopper",
    creator_email: "owner@example.com",
    creator_name: "Grace Hopper",
    llm_budget_usd: budget.usd,
    llm_budget_duration: budget.duration,
    llm_own_budget_usd: budget.own ?? null,
  };
}

const COVERED = {
  total_agents: 2,
  enrolled_agents: 2,
  uncovered: [],
  newly_enrolled: 0,
  spend_usd: 12.5,
  renews_at: "2026-10-01T00:00:00Z",
};

test.describe("Platform organization spend limit", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetOrganizationLlmCoverage({ coverage: COVERED });
  });

  test("a ceiling shows its amount and calendar window", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByRole("heading", { name: /model spend limit/i })).toBeVisible();
    await expect(page.getByText(/most this organization can spend is \$50\.00 per month/i)).toBeVisible();
    await expect(page.getByText(/can set a lower limit of its own/i)).toBeVisible();
  });

  test("a ceiling can never be removed, and an unchanged one is not re-sent", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByLabel("Spend limit (US dollars)", { exact: true })).toHaveValue("50");
    await expect(page.getByRole("button", { name: /remove limit/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();

    await page.getByLabel("Spend limit (US dollars)", { exact: true }).fill("");
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  test("the organization's own lower limit is shown as the one in force", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d", own: 20 }),
    });
    await page.goto(DETAIL_URL);

    await expect(
      page.getByText(/set its own lower limit of \$20\.00, which is the one in force/i),
    ).toBeVisible();
    // Spend is measured against the limit in force, not the ceiling.
    await expect(page.getByText(/\$12\.50 of \$20\.00 used/i)).toBeVisible();
  });

  test("a zero allowance is shown as zero", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 0, duration: "30d" }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/most this organization can spend is \$0\.00 per month/i)).toBeVisible();
  });

  test("saving sends the amount and the selected window", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    const requests = await data.organizations.interceptSetPlatformOrganizationLlmBudget({
      organization: organization({ usd: 25, duration: "7d" }),
    });
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit (US dollars)", { exact: true }).fill("25");
    await page.getByLabel("Renewal period").click();
    await page.getByRole("option", { name: "per week" }).click();
    await page.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => requests).toEqual([{ budget_usd: 25, budget_duration: "7d" }]);
  });

  test("a negative amount is refused before any request", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    const requests = await data.organizations.interceptSetPlatformOrganizationLlmBudget();
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit (US dollars)", { exact: true }).fill("-5");
    await page.getByLabel("Spend limit (US dollars)", { exact: true }).blur();
    await expect(page.getByText(/enter an amount of zero or more/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(requests).toEqual([]);
  });

  test("a failure to apply still shows the amount that was stored", async ({ page }) => {
    // The API stores the row before applying it, so a 502 means "saved, not applied".
    // The card must refetch rather than keep rendering the old value.
    let reads = 0;
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      reads += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          reads === 1
            ? organization({ usd: 20, duration: "30d" })
            : organization({ usd: 50, duration: "30d" }),
        ),
      });
    });
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}/llm-budget`, async (route) => {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Spend limit saved, but it could not be applied yet. It will be retried automatically.",
        }),
      });
    });
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit (US dollars)", { exact: true }).fill("50");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText(/could not be applied yet/i)).toBeVisible();
    await expect(page.getByText(/most this organization can spend is \$50\.00 per month/i)).toBeVisible();
  });
});

test.describe("Agents a limit does not cover yet", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  const PARTIAL = {
    total_agents: 3,
    enrolled_agents: 1,
    newly_enrolled: 0,
    uncovered: [
      { agent_id: "11111111-1111-4111-8111-111111111111", agent_name: "Scribe", status: "unenrolled" },
      { agent_id: "22222222-2222-4222-8222-222222222222", agent_name: "Borrowed", status: "other_team" },
    ],
  };

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
  });

  test("are named beside the controls, which stay usable", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmCoverage({ coverage: PARTIAL });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/2 of 3 agents aren't covered by this limit yet/i)).toBeVisible();
    await expect(page.getByText(/Scribe — not enrolled/i)).toBeVisible();
    await expect(page.getByText(/Borrowed — already assigned elsewhere/i)).toBeVisible();
    await expect(page.getByLabel("Spend limit (US dollars)", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /enroll agents/i })).toBeVisible();
  });

  test("enrolling them clears the notice", async ({ page }) => {
    let covered = false;
    await page.route(
      `**/api/v1/platform/organizations/${ORG_A_ID}/llm-budget/coverage`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            covered
              ? { total_agents: 3, enrolled_agents: 3, uncovered: [], newly_enrolled: 0 }
              : PARTIAL,
          ),
        });
      },
    );
    // Flipped inside the handler, not after the click: the refetch that follows the
    // mutation can land before a statement after click() runs.
    await page.route(
      `**/api/v1/platform/organizations/${ORG_A_ID}/llm-budget/enroll`,
      async (route) => {
        covered = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            total_agents: 3,
            enrolled_agents: 3,
            uncovered: [],
            newly_enrolled: 2,
          }),
        });
      },
    );
    await page.goto(DETAIL_URL);

    await page.getByRole("button", { name: /enroll agents/i }).click();

    await expect(page.getByRole("button", { name: /enroll agents/i })).toHaveCount(0);
  });

  test("an unknown coverage check never hides the controls", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmCoverage({ status: 503 });
    await page.goto(DETAIL_URL);

    await expect(page.getByLabel("Spend limit (US dollars)", { exact: true })).toBeVisible();
  });
});

test.describe("Spend against the limit", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptGetPlatformOrganizationMembers();
  });

  test("an exhausted limit says so", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 0.01, duration: "30d" }),
    });
    await data.organizations.interceptGetOrganizationLlmCoverage({
      coverage: { ...COVERED, total_agents: 1, enrolled_agents: 1, spend_usd: 0.011985 },
    });
    await page.goto(DETAIL_URL);

    // Sub-cent amounts must not collapse to $0.00, or a tiny limit reads as unused.
    await expect(page.getByText(/\$0\.0120 of \$0\.0100 used — limit reached/i)).toBeVisible();
  });

  test("an unreadable spend figure is unknown rather than zero", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await data.organizations.interceptGetOrganizationLlmCoverage({
      coverage: { ...COVERED, spend_usd: null, renews_at: null },
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/spend against this limit is unavailable right now/i)).toBeVisible();
    await expect(page.getByText(/\$0\.00 of/)).toHaveCount(0);
  });
});
