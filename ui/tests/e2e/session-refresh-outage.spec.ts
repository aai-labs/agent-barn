import { expect, test, type Route } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

// The access token lives only in memory, so every page load refreshes it. When the API
// is down that refresh fails, and that must not end a session whose refresh cookie is
// still good: only the server refusing the refresh does.
test.describe("Session refresh during an API outage", () => {
  let dashboardPage: DashboardPage;
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
  });

  const outages: Record<string, (route: Route) => Promise<void>> = {
    "answers 503": (route) =>
      route.fulfill({ status: 503, contentType: "text/plain", body: "Service Unavailable" }),
    "is unreachable": (route) => route.abort("connectionrefused"),
  };

  for (const [name, fail] of Object.entries(outages)) {
    test(`keeps the session when the API ${name}, and recovers on retry`, async ({ page }) => {
      // Registered last, so it wins over the mocks above until removed.
      const outage = (route: Route) => fail(route);
      await page.route("**/api/**", outage);

      await dashboardPage.goto();

      await expect(page.getByText("Can't reach Agent Barn")).toBeVisible();
      await expect(
        page.getByText(
          "The server isn't responding right now. You're still signed in. Try again in a moment.",
        ),
      ).toBeVisible();
      await expect(page).toHaveURL(/\/dashboard\//);

      await page.unroute("**/api/**", outage);
      await page.getByRole("button", { name: "Try again" }).click();

      await expect(page.getByRole("heading", { name: /your team/i })).toBeVisible();
      await expect(page).toHaveURL(/\/dashboard\//);
    });
  }

  test("shows the account error, not the outage one, when the API refuses the account", async ({
    page,
  }) => {
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Bad request" }),
      }),
    );

    await dashboardPage.goto();

    await expect(page.getByText("We couldn't load your account")).toBeVisible();
    await expect(page.getByText("Your account details are unavailable right now.")).toBeVisible();
    await expect(page.getByText("Can't reach Agent Barn")).toHaveCount(0);
    await expect(page.getByText(/session is valid/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Retry account" })).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard\//);
  });

  test("ends the session when the server refuses the refresh", async ({ page }) => {
    await page.route("**/api/v1/auth/refresh", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Invalid refresh token" }),
      }),
    );

    await dashboardPage.goto();

    await expect(page).toHaveURL(/\/login/);
  });
});
