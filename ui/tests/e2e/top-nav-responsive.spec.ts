import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

/**
 * The top nav is a single flex row whose children default to `min-width: auto`,
 * so without explicit shrink rules it forces the page wider than the viewport
 * instead of adapting. Below `lg` the tabs move into a drawer; at `lg` and up
 * they stay inline. `lg` is the threshold because Platform view needs ~1079px
 * to lay its tabs out at full spacing, so every tablet width gets the drawer.
 * These specs pin the outcomes — the page never scrolls sideways and every tab
 * stays reachable — not the utilities behind them.
 */
test.describe("Top nav responsiveness", () => {
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
  });

  const horizontalOverflow = (page: import("@playwright/test").Page) =>
    page.evaluate(() => {
      const root = document.documentElement;
      return root.scrollWidth - root.clientWidth;
    });

  test.describe("on a mobile viewport", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("does not scroll the organization view horizontally", async ({
      page,
    }) => {
      await dashboardPage.goto();
      await expect(page.locator("header")).toBeVisible();

      expect(await horizontalOverflow(page)).toBe(0);
    });

    test("does not scroll the platform view horizontally", async ({ page }) => {
      // Platform view carries the most tabs, so it overflows first.
      await dashboardPage.gotoUsers();
      await expect(page.locator("header")).toBeVisible();

      expect(await horizontalOverflow(page)).toBe(0);
    });

    test("collapses the tabs into a navigation drawer", async ({ page }) => {
      await dashboardPage.gotoUsers();

      // The inline tab row is hidden; the trigger replaces it.
      await expect(page.locator("header nav")).toBeHidden();

      const trigger = page.getByRole("button", { name: "Open navigation" });
      await expect(trigger).toBeVisible();
      await trigger.click();

      const drawer = page.getByRole("dialog");
      await expect(drawer).toBeVisible();
      await expect(drawer.getByRole("link", { name: "Organizations" })).toBeVisible();
    });

    test("closes the drawer when a destination is chosen", async ({ page }) => {
      await dashboardPage.gotoUsers();

      await page.getByRole("button", { name: "Open navigation" }).click();

      const drawer = page.getByRole("dialog");
      await drawer.getByRole("link", { name: "Overview" }).click();

      await expect(drawer).toBeHidden();
    });
  });

  test.describe("on a tablet viewport", () => {
    test.use({ viewport: { width: 900, height: 900 } });

    test("uses the drawer rather than cutting the tab row off", async ({
      page,
    }) => {
      await dashboardPage.gotoUsers();

      await expect(page.locator("header nav")).toBeHidden();
      await expect(
        page.getByRole("button", { name: "Open navigation" }),
      ).toBeVisible();

      expect(await horizontalOverflow(page)).toBe(0);
    });
  });

  test.describe("at the narrowest inline width", () => {
    test.use({ viewport: { width: 1024, height: 900 } });

    test("fits every tab without an internal scroll", async ({ page }) => {
      await dashboardPage.gotoUsers();

      const nav = page.locator("header nav");
      await expect(nav).toBeVisible();

      const navCutOff = await nav.evaluate(
        (el) => el.scrollWidth > el.clientWidth,
      );

      expect(navCutOff).toBe(false);
      expect(await horizontalOverflow(page)).toBe(0);
    });
  });

  test.describe("on a desktop viewport", () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test("keeps the tabs inline and hides the drawer trigger", async ({
      page,
    }) => {
      await dashboardPage.gotoUsers();

      const nav = page.locator("header nav");
      await expect(nav).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Open navigation" }),
      ).toBeHidden();

      const navOverflows = await nav.evaluate(
        (el) => el.scrollWidth > el.clientWidth,
      );

      expect(navOverflows).toBe(false);
      expect(await horizontalOverflow(page)).toBe(0);
    });
  });
});
