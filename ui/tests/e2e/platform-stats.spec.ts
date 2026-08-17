import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { PlatformStatsPage } from "../pages/platform-stats-page.po";

test.describe("Platform Stats Page", () => {
  let platformPage: PlatformStatsPage;
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    platformPage = new PlatformStatsPage(page);
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.platformStats.interceptGetMessageStatsRequest();
    await dataSupport.platformStats.interceptGetAgentStatsRequest();
  });

  test("renders the Overview and Activity sections for a platform admin", async () => {
    await platformPage.goto();

    await expect(platformPage.heading()).toBeVisible();
    await expect(platformPage.overviewHeading()).toBeVisible();
    await expect(platformPage.activityHeading()).toBeVisible();
  });

  test("shows the error state when stats endpoints fail", async () => {
    await dataSupport.platformStats.interceptGetMessageStatsRequest({
      status: 500,
      detail: "Stats service unavailable",
    });
    await dataSupport.platformStats.interceptGetAgentStatsRequest({
      status: 500,
      detail: "Stats service unavailable",
    });

    await platformPage.goto();

    await expect(
      platformPage.page.getByText("We couldn't load platform stats"),
    ).toBeVisible();
  });
});
