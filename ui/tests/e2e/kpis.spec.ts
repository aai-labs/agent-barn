import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { KpisPage } from "../pages/kpis-page.po";

const HOME_URL = `/dashboard/${TEST_ORG_ID}`;
const KPIS_URL = `${HOME_URL}/kpis`;

/** The default fixture is a platform-admin Owner, and platform admins can manage
 *  any org, so a Member needs both of those stripped. */
function memberContext() {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({
      ...membership,
      role: "MEMBER",
    })),
  };
}

test.describe("Organization KPIs — navigation and access", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
  });

  test.describe("on a desktop viewport", () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test("an owner finds KPIs right after Costs and opens the page", async ({ page }) => {
      await kpis.gotoHome();
      await expect(kpis.inlineNavLink("Costs")).toBeVisible();

      const labels = await kpis.inlineNavLinks().allInnerTexts();
      expect(labels.indexOf("KPIs")).toBe(labels.indexOf("Costs") + 1);

      await kpis.inlineNavLink("KPIs").click();

      await expect(page).toHaveURL(KPIS_URL);
      await expect(kpis.heading()).toBeVisible();
      await expect(kpis.inlineNavLink("KPIs")).toHaveAttribute("aria-current", "page");
    });

    test("a member does not see the KPIs entry", async ({ page }) => {
      await data.users.interceptGetUserContextRequest({ userContext: memberContext() });

      await kpis.gotoHome();

      await expect(kpis.inlineNavLink("Home")).toBeVisible();
      await expect(kpis.inlineNavLink("KPIs")).toHaveCount(0);
      expect(page.url()).toContain(HOME_URL);
    });

    test("a member who opens the KPIs URL is sent to the organization home", async ({ page }) => {
      await data.users.interceptGetUserContextRequest({ userContext: memberContext() });

      await kpis.goto();

      await expect(page).toHaveURL(HOME_URL);
      await expect(kpis.heading()).toHaveCount(0);
    });
  });

  test.describe("on a mobile viewport", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("an owner finds KPIs right after Costs in the navigation drawer", async ({ page }) => {
      await kpis.gotoHome();
      await kpis.openNavigationDrawer();
      await expect(kpis.drawerLink("Costs")).toBeVisible();

      const labels = await kpis.drawerLinks().allInnerTexts();
      expect(labels.indexOf("KPIs")).toBe(labels.indexOf("Costs") + 1);

      await kpis.drawerLink("KPIs").click();

      await expect(page).toHaveURL(KPIS_URL);
      await expect(kpis.heading()).toBeVisible();
    });

    test("a member does not see the KPIs entry in the navigation drawer", async () => {
      await data.users.interceptGetUserContextRequest({ userContext: memberContext() });

      await kpis.gotoHome();
      await kpis.openNavigationDrawer();

      await expect(kpis.drawerLink("Home")).toBeVisible();
      await expect(kpis.drawerLink("KPIs")).toHaveCount(0);
    });
  });
});
