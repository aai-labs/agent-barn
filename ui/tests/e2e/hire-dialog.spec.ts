import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

test.describe("Hire Dialog", () => {
  test.describe.configure({ mode: "serial" });
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("should open the hire dialog", async ({ page }) => {
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
  });

  test("should navigate to step 2", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("A few details and we'll get them set up.")).toBeVisible();
  });

  test("should close the hire dialog", async ({ page }) => {
    await page.getByRole("button", { name: /cancel/i }).click();

    await expect(page.getByText("What kind of teammate do you need?")).not.toBeVisible();
  });
});
