import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

test.describe("Dashboard Page", () => {
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
  });

  test("should load dashboard", async () => {
    await dashboardPage.goto();

    await expect(dashboardPage.heading()).toBeVisible();
  });

  test("shows an account error state when user context fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetUserContextRequest({
      status: 500,
      detail: "Account service unavailable",
    });

    await dashboardPage.goto();

    await expect(
      page.getByText("We couldn't load your account"),
    ).toBeVisible();
    await expect(
      page.getByText("Account service unavailable"),
    ).toBeVisible();
  });

  test("shows an inline error state when a later users search fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetUsersRequest({
      status: 500,
      detail: "Users service unavailable",
      failAfterRequests: 1,
    });

    await dashboardPage.gotoUsers();
    await dashboardPage.searchInput("Search users").fill("ada");

    await expect(
      page.getByText("We couldn't load users"),
    ).toBeVisible();
    await expect(page.getByText("Users service unavailable")).toBeVisible();
  });

  test("shows an inline error state when a later organizations search fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetOrganizationsRequest({
      status: 500,
      detail: "Organizations service unavailable",
      failAfterRequests: 1,
    });

    await dashboardPage.gotoOrganizations();
    await dashboardPage.searchInput("Search organizations").fill("aai");

    await expect(
      page.getByText("We couldn't load organizations"),
    ).toBeVisible();
    await expect(
      page.getByText("Organizations service unavailable"),
    ).toBeVisible();
  });
});
