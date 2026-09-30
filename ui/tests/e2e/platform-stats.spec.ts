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

  test("narrows by an explicit date range rather than preset periods", async () => {
    await platformPage.goto();

    await expect(platformPage.periodSelect()).toHaveCount(0);
    await expect(platformPage.dateRangePicker()).toBeVisible();
  });

  test("puts a thirty day window in the URL on first load", async ({ page }) => {
    await platformPage.goto();

    await expect(page).toHaveURL(/[?&]from=/);
    const params = new URL(page.url()).searchParams;
    const spanDays = Math.round(
      (new Date(params.get("to")!).getTime() -
        new Date(params.get("from")!).getTime()) /
        86_400_000,
    );
    expect(spanDays).toBe(30);
  });

  test("restores the whole view from a shared link", async ({ page }) => {
    await page.goto(
      "/dashboard/platform?from=2026-07-01T00:00:00.000Z&to=2026-07-31T23:59:59.999Z&app=telegram&direction=inbound",
    );

    await expect(platformPage.messagingAppSelect()).toContainText("Telegram");
    await expect(platformPage.directionSelect()).toContainText("Received only");
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

  test("zeroes the other direction when one is selected", async () => {
    await platformPage.goto();
    await platformPage.directionSelect().click();

    await expect(platformPage.openOptions()).toHaveText([
      "All messages",
      "Received only",
      "Sent only",
    ]);

    await platformPage.chooseOption("Received only");

    await expect(platformPage.statTile("Received")).toHaveText("120");
    await expect(platformPage.statTile("Sent")).toHaveText("0");
    await expect(platformPage.statTile("Messages")).toHaveText("120");
  });

  test("mirrors filters to the URL without navigating", async ({ page }) => {
    await platformPage.goto();
    await expect(platformPage.statTile("Messages")).toHaveText("200");

    // A router navigation refetches the RSC payload. Filters must not: on a
    // prerendered route that write is not observed, so anything reading it back
    // re-fires forever. Matched by the signature of our own writes — `from` is
    // always emitted — because a production build also prefetches this route and
    // its siblings, and those carry no panel state.
    const navigations: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        url.pathname === "/dashboard/platform" &&
        url.searchParams.has("_rsc") &&
        url.searchParams.has("from")
      ) {
        navigations.push(request.url());
      }
    });

    await platformPage.directionSelect().click();
    await platformPage.chooseOption("Received only");
    await expect(platformPage.statTile("Sent")).toHaveText("0");

    await platformPage.messagingAppSelect().click();
    await platformPage.chooseOption("Telegram");
    await expect(page).toHaveURL(/app=telegram/);

    expect(navigations).toHaveLength(0);
  });

  test("keeps a filter pressed immediately after load", async ({ page }) => {
    // Deliberately no settling: this races the default-window write.
    await page.goto("/dashboard/platform");
    await platformPage.directionSelect().click();
    await platformPage.chooseOption("Received only");

    await expect(platformPage.statTile("Sent")).toHaveText("0");
    await expect(page).toHaveURL(/direction=inbound/);
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
