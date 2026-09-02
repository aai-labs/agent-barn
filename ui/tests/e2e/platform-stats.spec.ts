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

  test("offers reporting periods that do not overlap each other", async () => {
    await platformPage.goto();
    await platformPage.periodSelect().click();

    await expect(platformPage.openOptions()).toHaveText([
      "Last hour",
      "Last 6 hours",
      "Last 12 hours",
      "This week",
      "This month",
      "This year",
      "Custom range",
    ]);
  });

  test("offers every messaging app an agent can be connected to", async () => {
    await platformPage.goto();
    await platformPage.messagingAppSelect().click();

    await expect(platformPage.openOptions()).toHaveText([
      "All messaging apps",
      "Slack",
      "Teams",
      "Telegram",
      "Discord",
    ]);
  });

  test("leaves an anchored period open so its window keeps advancing", async ({
    page,
  }) => {
    const statsRequest = page.waitForRequest((request) =>
      request.url().includes("/api/v1/platform/stats/messages"),
    );

    await platformPage.goto();

    const url = new URL((await statsRequest).url());
    expect(url.searchParams.get("from_date")).not.toBeNull();
    expect(url.searchParams.get("to_date")).toBeNull();
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
