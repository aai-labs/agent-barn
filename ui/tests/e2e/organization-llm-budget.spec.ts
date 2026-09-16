import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { ORG_A_ID } from "../pages/data-support/organization-data-support.po";

const DETAIL_URL = `/dashboard/platform/organizations/${ORG_A_ID}`;

function organization(budget: { usd: number | null; duration: string | null }) {
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
  };
}

test.describe("Platform organization LLM budget", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptGetPlatformOrganizationMembers();
    // Fully covered by default; the gate has its own describe block below.
    await data.organizations.interceptGetOrganizationLlmCoverage({
      coverage: {
        total_agents: 2,
        enrolled_agents: 2,
        uncovered: [],
        newly_enrolled: 0,
        spend_usd: 12.5,
        renews_at: "2026-10-01T00:00:00Z",
      },
    });
  });

  test("an organization with no ceiling reads as unlimited", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: null, duration: null }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByRole("heading", { name: /model spend limit/i })).toBeVisible();
    await expect(page.getByText(/currently no limit/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /remove limit/i })).toHaveCount(0);
  });

  test("a configured ceiling shows its amount and window", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/currently \$50 per 30 days/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /remove limit/i })).toBeVisible();
  });

  test("a zero allowance is not shown as no limit", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 0, duration: "30d" }),
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/currently \$0 per 30 days/i)).toBeVisible();
  });

  test("saving sends the amount and the selected window", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: null, duration: null }),
    });
    const requests = await data.organizations.interceptSetPlatformOrganizationLlmBudget({
      organization: organization({ usd: 25, duration: "7d" }),
    });
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit in USD").fill("25");
    await page.getByLabel("Budget window").selectOption("7d");
    await page.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => requests).toEqual([{ budget_usd: 25, budget_duration: "7d" }]);
  });

  test("removing the limit clears the amount and the window together", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    const requests = await data.organizations.interceptSetPlatformOrganizationLlmBudget({
      organization: organization({ usd: null, duration: null }),
    });
    await page.goto(DETAIL_URL);

    await page.getByRole("button", { name: /remove limit/i }).click();

    await expect.poll(() => requests).toEqual([{ budget_usd: null, budget_duration: null }]);
  });

  test("a negative amount is refused before any request", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: null, duration: null }),
    });
    const requests = await data.organizations.interceptSetPlatformOrganizationLlmBudget();
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit in USD").fill("-5");
    await expect(page.getByText(/enter a positive amount/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(requests).toEqual([]);
  });

  test("a proxy failure still shows the amount that was stored", async ({ page }) => {
    // The API stores the row before pushing to LiteLLM, so a 502 means "saved, not
    // applied". The card must refetch rather than keep rendering the old value.
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
          reads === 1 ? organization({ usd: null, duration: null }) : organization({ usd: 50, duration: "30d" }),
        ),
      });
    });
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}/llm-budget`, async (route) => {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Budget saved but the LLM proxy could not be updated; it will be retried automatically",
        }),
      });
    });
    await page.goto(DETAIL_URL);

    await page.getByLabel("Spend limit in USD").fill("50");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText(/proxy could not be updated/i)).toBeVisible();
    await expect(page.getByText(/currently \$50 per 30 days/i)).toBeVisible();
  });
});

test.describe("Enrollment gate", () => {
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
  });

  test("an organization with unenrolled agents cannot be given a limit yet", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: null, duration: null }),
    });
    await data.organizations.interceptGetOrganizationLlmCoverage({ coverage: PARTIAL });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/2 of 3 agents aren't enrolled yet/i)).toBeVisible();
    // Named, so an administrator can see what a limit would miss and why.
    await expect(page.getByText(/Scribe — not enrolled/i)).toBeVisible();
    await expect(page.getByText(/Borrowed — already assigned elsewhere/i)).toBeVisible();
    await expect(page.getByLabel("Spend limit in USD")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /enroll agents/i })).toBeVisible();
  });

  test("enrolling reveals the limit controls", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: null, duration: null }),
    });
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

    await expect(page.getByLabel("Spend limit in USD")).toBeVisible();
    await expect(page.getByRole("button", { name: /enroll agents/i })).toHaveCount(0);
  });

  test("an organization that already has a limit is never gated out of removing it", async ({
    page,
  }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await data.organizations.interceptGetOrganizationLlmCoverage({ coverage: PARTIAL });
    await page.goto(DETAIL_URL);

    await expect(page.getByRole("button", { name: /remove limit/i })).toBeVisible();
    // Still told the truth about what the existing limit does not cover.
    await expect(page.getByText(/2 of 3 agents are not covered/i)).toBeVisible();
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
      coverage: {
        total_agents: 1,
        enrolled_agents: 1,
        uncovered: [],
        newly_enrolled: 0,
        spend_usd: 0.011985,
        renews_at: "2026-10-01T00:00:00Z",
      },
    });
    await page.goto(DETAIL_URL);

    // Sub-cent amounts must not collapse to $0.00, or a tiny limit reads as unused.
    await expect(page.getByText(/\$0\.0120 of \$0\.0100 used — exhausted/i)).toBeVisible();
  });

  test("an unreadable proxy leaves spend unknown rather than showing zero", async ({ page }) => {
    await data.organizations.interceptGetPlatformOrganization({
      organization: organization({ usd: 50, duration: "30d" }),
    });
    await data.organizations.interceptGetOrganizationLlmCoverage({
      coverage: {
        total_agents: 1,
        enrolled_agents: 1,
        uncovered: [],
        newly_enrolled: 0,
        spend_usd: null,
        renews_at: null,
      },
    });
    await page.goto(DETAIL_URL);

    await expect(page.getByText(/spend against this limit is unavailable right now/i)).toBeVisible();
    await expect(page.getByText(/\$0\.00 of/)).toHaveCount(0);
  });
});
