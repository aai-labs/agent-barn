import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  activityTotals,
  isKpiRead,
  organizationActivity,
  organizationValue,
  valueTotals,
} from "../pages/data-support/kpis-data-support.po";
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

    test("a member never asks for value or activity figures", async ({ page }) => {
      await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
      await data.kpis.interceptValue({ status: 403 });
      await data.kpis.interceptActivity({ status: 403 });
      const kpiReads: string[] = [];
      page.on("request", (request) => {
        if (isKpiRead(request)) kpiReads.push(request.url());
      });

      await kpis.goto();
      await expect(page).toHaveURL(HOME_URL);
      await expect(kpis.inlineNavLink("Home")).toBeVisible();

      expect(kpiReads).toEqual([]);
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

test.describe("Organization KPIs — headline tiles", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
  });

  test("shows every headline figure with its coverage", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.5 h");
    await expect(kpis.tile("kpi-hours-saved")).toContainText("12 successful writes");
    await expect(kpis.tile("kpi-value")).toContainText("$150.00");
    await expect(kpis.tile("kpi-value")).toContainText("at $60.00/h");
    await expect(kpis.tile("kpi-spend")).toContainText("$12.40");
    await expect(kpis.tile("kpi-value-per-dollar")).toContainText("$12.10 per $1");
    await expect(kpis.tile("kpi-requests")).toContainText("480");
    await expect(kpis.tile("kpi-handled")).toContainText("75%");
    await expect(kpis.tile("kpi-handled")).toContainText("based on 120 of 480 requests");
    await expect(kpis.tile("kpi-handled")).toContainText("Web Chat and Email only");
  });

  test("without an hourly rate, value asks for one instead of showing $0", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({
        totals: valueTotals({ value: null, value_to_spend_ratio: null, hourly_rate_usd: null }),
      }),
    });
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.tile("kpi-value")).toContainText("Set an hourly rate");
    await expect(kpis.tile("kpi-value-per-dollar")).toContainText("Set an hourly rate");
    await expect(kpis.tile("kpi-value")).not.toContainText("$0");
    await expect(kpis.tile("kpi-value-per-dollar")).not.toContainText("$0");
    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.5 h");
  });

  test("the reason a figure is missing is shown in full, not cut off", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({
        totals: valueTotals({ value: null, value_to_spend_ratio: null, hourly_rate_usd: null }),
      }),
    });
    await data.kpis.interceptActivity({
      body: organizationActivity({
        totals: activityTotals({ handled_without_failure_rate: null, handled_coverage: 0 }),
      }),
    });

    await kpis.goto();

    for (const [tile, reason] of [
      ["kpi-value", "Set an hourly rate"],
      ["kpi-value-per-dollar", "Set an hourly rate"],
      ["kpi-handled", "not enough data"],
    ]) {
      const text = kpis.tile(tile).getByText(reason);
      await expect(text).toBeVisible();
      const cutOff = await text.evaluate((el) => el.scrollWidth > el.clientWidth);
      expect(cutOff, `"${reason}" is cut off in ${tile}`).toBe(false);
    }
  });

  test("with a rate but no spend, value per dollar reports not enough data", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({
        totals: valueTotals({ spend: 0, value_to_spend_ratio: null }),
      }),
    });
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.tile("kpi-value-per-dollar")).toContainText("not enough data");
    await expect(kpis.tile("kpi-value-per-dollar")).not.toContainText("Set an hourly rate");
  });

  test("an unknown handled rate is not reported as 0%", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity({
      body: organizationActivity({
        totals: activityTotals({ handled_without_failure_rate: null, handled_coverage: 0 }),
      }),
    });

    await kpis.goto();

    await expect(kpis.tile("kpi-handled")).toContainText("not enough data");
    await expect(kpis.tile("kpi-handled")).toContainText("based on 0 of 480 requests");
    await expect(kpis.tile("kpi-handled")).not.toContainText("0%");
  });

  test("small but real figures do not round to zero or to a perfect score", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({ totals: valueTotals({ minutes_saved: 2, successful_writes: 1 }) }),
    });
    await data.kpis.interceptActivity({
      body: organizationActivity({
        totals: activityTotals({ handled_without_failure_rate: 0.996 }),
      }),
    });

    await kpis.goto();

    await expect(kpis.tile("kpi-hours-saved")).toContainText("<0.1 h");
    await expect(kpis.tile("kpi-handled")).toContainText("99.6%");
  });

  test("with no range chosen, the server's default window is used and shown", async () => {
    const value = await data.kpis.interceptValue();
    const activity = await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.windowLabel()).toContainText("last 30 days");
    expect(value.requests[0].search).toBe("");
    expect(activity.requests[0].search).toBe("");
  });

  test("a chosen date range lands in the URL and bounds both reads", async ({ page }) => {
    const value = await data.kpis.interceptValue();
    const activity = await data.kpis.interceptActivity();
    await kpis.goto();
    await expect(kpis.tile("kpi-requests")).toContainText("480");

    await kpis.chooseDateRange();

    await expect(page).toHaveURL(/from=/);
    await expect(page).toHaveURL(/to=/);
    const url = new URL(page.url());
    await expect
      .poll(() => value.requests.at(-1)?.searchParams.get("from_date"))
      .toBe(url.searchParams.get("from"));
    expect(value.requests.at(-1)?.searchParams.get("to_date")).toBe(url.searchParams.get("to"));
    await expect
      .poll(() => activity.requests.at(-1)?.searchParams.get("from_date"))
      .toBe(url.searchParams.get("from"));
    expect(activity.requests.at(-1)?.searchParams.get("to_date")).toBe(url.searchParams.get("to"));
  });

  test("the spend tile links to Costs with the same range", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
    const from = "2026-09-01T00:00:00.000Z";
    const to = "2026-09-15T23:59:59.999Z";

    await kpis.gotoWithRange(from, to);

    const href = await kpis.spendLink().getAttribute("href");
    const link = new URL(href!, "http://localhost");
    expect(link.pathname).toBe(`/dashboard/${TEST_ORG_ID}/costs`);
    expect(link.searchParams.get("from")).toBe(from);
    expect(link.searchParams.get("to")).toBe(to);
  });

  test("the spend tile links to Costs without a range when none is chosen", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.spendLink()).toHaveAttribute("href", `/dashboard/${TEST_ORG_ID}/costs`);
  });

  test("a failed activity read only affects its own tiles, and retry recovers", async () => {
    await data.kpis.interceptValue();
    const activity = await data.kpis.interceptActivity({ status: 500 });

    await kpis.goto();

    await expect(kpis.tile("kpi-requests")).toContainText("Unable to load");
    await expect(kpis.tile("kpi-handled")).toContainText("Unable to load");
    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.5 h");
    await expect(kpis.tile("kpi-spend")).toContainText("$12.40");

    activity.respondWith({ status: 200 });
    await kpis.retryTile("kpi-requests");

    await expect(kpis.tile("kpi-requests")).toContainText("480");
    await expect(kpis.tile("kpi-handled")).toContainText("75%");
  });

  test("a failed value read only affects its own tiles, and retry recovers", async () => {
    const value = await data.kpis.interceptValue({ status: 500 });
    await data.kpis.interceptActivity();

    await kpis.goto();

    for (const tile of ["kpi-hours-saved", "kpi-value", "kpi-spend", "kpi-value-per-dollar"]) {
      await expect(kpis.tile(tile)).toContainText("Unable to load");
    }
    await expect(kpis.tile("kpi-requests")).toContainText("480");

    value.respondWith({ status: 200 });
    await kpis.retryTile("kpi-value");

    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.5 h");
    await expect(kpis.tile("kpi-spend")).toContainText("$12.40");
  });
});
