import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  KPI_AGENT_B_ID,
  activityAgent,
  activityTotals,
  isKpiRead,
  organizationActivity,
  organizationValue,
  valueAgent,
  valueSettings,
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

test.describe("Organization KPIs — trend chart", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
  });

  test("opens on value against spend and switches to requests", async ({ page }) => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.chartTab("Value vs spend")).toHaveAttribute("aria-selected", "true");
    await expect(kpis.chartAreas("kpi-value-chart")).toHaveCount(2);

    await kpis.showChart("Requests");

    await expect(kpis.chartTab("Requests")).toHaveAttribute("aria-selected", "true");
    await expect(kpis.chartAreas("kpi-requests-chart")).toHaveCount(1);
    await expect(page.getByTestId("kpi-value-chart")).toHaveCount(0);
  });

  test("without an hourly rate, charts spend alone and says why", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({
        totals: valueTotals({ value: null, value_to_spend_ratio: null, hourly_rate_usd: null }),
        series: [
          { bucket: "2026-09-30T00:00:00Z", minutes_saved: 60, value: null, spend: 4.1 },
          { bucket: "2026-10-01T00:00:00Z", minutes_saved: 90, value: null, spend: 8.3 },
        ],
      }),
    });
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.trend()).toContainText("Set an hourly rate to chart value");
    await expect(kpis.chartAreas("kpi-value-chart")).toHaveCount(1);
  });

  test("a failed value read leaves the requests chart working", async () => {
    await data.kpis.interceptValue({ status: 500 });
    await data.kpis.interceptActivity();

    await kpis.goto();

    await expect(kpis.trend()).toContainText("Unable to load");
    await expect(kpis.trend().getByRole("button", { name: "Retry" })).toBeVisible();

    await kpis.showChart("Requests");

    await expect(kpis.chartAreas("kpi-requests-chart")).toHaveCount(1);
  });

  test("a failed activity read leaves the value chart working, and retry recovers", async () => {
    await data.kpis.interceptValue();
    const activity = await data.kpis.interceptActivity({ status: 500 });

    await kpis.goto();

    await expect(kpis.chartAreas("kpi-value-chart")).toHaveCount(2);

    await kpis.showChart("Requests");
    await expect(kpis.trend()).toContainText("Unable to load");

    activity.respondWith({ status: 200 });
    await kpis.retryTrend();

    await expect(kpis.chartAreas("kpi-requests-chart")).toHaveCount(1);
  });
});

const KPI_AGENT_DELETED_ID = "66666666-6666-4666-8666-666666666666";
const KPI_AGENT_ACTIVITY_ONLY_ID = "77777777-7777-4777-8777-777777777777";

function tableValue(overrides: Record<string, unknown> = {}) {
  return organizationValue({
    agents: [
      valueAgent(),
      valueAgent({
        agent_id: KPI_AGENT_B_ID,
        agent_name: "Meti",
        successful_writes: 2,
        minutes_saved: 30,
        value: 30,
        spend: 3,
        value_to_spend_ratio: 10,
      }),
      valueAgent({
        agent_id: null,
        agent_name: "Unattributed",
        successful_writes: 0,
        minutes_saved: 0,
        value: 0,
        spend: 0.5,
        value_to_spend_ratio: 0,
      }),
      valueAgent({
        agent_id: KPI_AGENT_DELETED_ID,
        agent_name: null,
        agent_deleted: true,
        successful_writes: 1,
        minutes_saved: 6,
        value: 6,
        spend: 0.2,
        value_to_spend_ratio: 30,
      }),
    ],
    ...overrides,
  });
}

function tableActivity() {
  const idle = {
    requests: 0,
    handled_without_failure_rate: null,
    handled_coverage: 0,
    median_response_seconds: null,
    response_time_coverage: 0,
    cost_per_request: null,
    tool_calls_per_request: null,
  };
  return organizationActivity({
    agents: [
      activityAgent({
        requests: 400,
        handled_coverage: 100,
        response_time_coverage: 80,
        cost_per_request: 0.0235,
      }),
      activityAgent({
        agent_id: KPI_AGENT_B_ID,
        agent_name: "Meti",
        requests: 80,
        handled_without_failure_rate: 0.9,
        handled_coverage: 20,
        median_response_seconds: 125,
        response_time_coverage: 18,
        cost_per_request: 0.0375,
        tool_calls_per_request: 2,
        spend: 3,
      }),
      activityAgent({
        agent_id: KPI_AGENT_ACTIVITY_ONLY_ID,
        agent_name: "Ora",
        requests: 200,
        handled_without_failure_rate: null,
        handled_coverage: 0,
        median_response_seconds: null,
        response_time_coverage: 0,
        cost_per_request: 0,
        tool_calls_per_request: 0.5,
        spend: 0,
      }),
      activityAgent({ ...idle, agent_id: null, agent_name: "Unattributed", spend: 0.5 }),
      activityAgent({
        ...idle,
        agent_id: KPI_AGENT_DELETED_ID,
        agent_name: null,
        agent_deleted: true,
        spend: 0.2,
      }),
    ],
  });
}

test.describe("Organization KPIs — agents table and footnotes", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
  });

  test("lists every agent from both reads, ranked by hours saved", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();
    await expect(kpis.agentTable()).toBeVisible();

    expect(await kpis.agentNames()).toEqual([
      "Aria",
      "Meti",
      "Deleted agent",
      "Unattributed",
      "Ora",
    ]);
    await expect(kpis.columnHeader("Hours saved")).toHaveAttribute("aria-sort", "descending");
  });

  test("shows each agent's value and activity figures with their coverage", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.agentCell("Aria", "value")).toHaveText("$120.00");
    await expect(kpis.agentCell("Aria", "hours")).toHaveText("2.0 h");
    await expect(kpis.agentCell("Aria", "spend")).toHaveText("$9.40");
    await expect(kpis.agentCell("Aria", "ratio")).toHaveText("$12.77 per $1");
    await expect(kpis.agentCell("Aria", "requests")).toHaveText("400");
    await expect(kpis.agentCell("Aria", "handled")).toHaveText("75% · 100 reqs");
    await expect(kpis.agentCell("Aria", "median")).toHaveText("1.5 s · 80 reqs");
    await expect(kpis.agentCell("Aria", "costPerRequest")).toHaveText("$0.02");
    await expect(kpis.agentCell("Aria", "toolCalls")).toHaveText("1.4");
    await expect(kpis.agentCell("Meti", "median")).toHaveText("2m 05s · 18 reqs");
  });

  test("an agent with requests but no writes or spend reads zero value, not unknown", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.agentCell("Ora", "hours")).toHaveText("0.0 h");
    await expect(kpis.agentCell("Ora", "spend")).toHaveText("$0.00");
    await expect(kpis.agentCell("Ora", "ratio")).toHaveText("not enough data");
    await expect(kpis.agentCell("Ora", "handled")).toHaveText("not enough data");
    await expect(kpis.agentCell("Ora", "median")).toHaveText("not enough data");
  });

  test("names unattributed spend and marks deleted agents", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.agentRow("Unattributed").locator("[data-agent-name]")).toHaveText(
      "Unattributed",
    );
    await expect(kpis.agentRow("Unattributed")).not.toContainText("Deleted");
    await expect(kpis.agentRow("Deleted agent")).toContainText("Deleted");
    await expect(kpis.agentCell("Deleted agent", "spend")).toHaveText("$0.20");
  });

  test("sorts by any column, reverses on a second click, and keeps unknowns last", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });
    await kpis.goto();
    await expect(kpis.agentTable()).toBeVisible();

    await kpis.sortBy("Requests");
    expect((await kpis.agentNames()).slice(0, 3)).toEqual(["Aria", "Ora", "Meti"]);

    await kpis.sortBy("Requests");
    expect((await kpis.agentNames()).slice(-3)).toEqual(["Meti", "Ora", "Aria"]);

    await kpis.sortBy("Median response");
    expect((await kpis.agentNames()).slice(0, 2)).toEqual(["Meti", "Aria"]);

    await kpis.sortBy("Median response");
    const ascending = await kpis.agentNames();
    expect(ascending.slice(0, 2)).toEqual(["Aria", "Meti"]);
    expect(ascending.slice(2)).toContain("Ora");
  });

  test("without an hourly rate, agent value asks for one", async () => {
    const noRate = { value: null, value_to_spend_ratio: null };
    await data.kpis.interceptValue({
      body: tableValue({
        totals: valueTotals({ value: null, value_to_spend_ratio: null, hourly_rate_usd: null }),
        agents: [valueAgent(noRate)],
        top_outcome_types: [
          {
            outcome_type: "PULL_REQUEST_OPENED",
            successful_writes: 5,
            effective_minutes: 20,
            minutes_saved: 100,
            value: null,
          },
        ],
      }),
    });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.agentCell("Aria", "value")).toHaveText("Set an hourly rate");
    await expect(kpis.agentCell("Aria", "ratio")).toHaveText("Set an hourly rate");
    await expect(kpis.agentCell("Ora", "value")).toHaveText("Set an hourly rate");
    await expect(kpis.topOutcomes().first()).toContainText("Set an hourly rate");
  });

  test("a failed activity read blanks only its columns, and retry recovers", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    const activity = await data.kpis.interceptActivity({ status: 500 });

    await kpis.goto();

    await expect(kpis.agentTable()).toContainText("Unable to load activity figures");
    await expect(kpis.agentCell("Aria", "requests")).toHaveText("—");
    await expect(kpis.agentCell("Aria", "handled")).toHaveText("—");
    await expect(kpis.agentCell("Aria", "value")).toHaveText("$120.00");

    activity.respondWith({ status: 200, body: tableActivity() });
    await kpis.retryAgentTable();

    await expect(kpis.agentCell("Aria", "requests")).toHaveText("400");
    await expect(kpis.agentTable()).not.toContainText("Unable to load");
  });

  test("a failed value read blanks only its columns and the outcome footnotes", async () => {
    await data.kpis.interceptValue({ status: 500 });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.agentTable()).toContainText("Unable to load value figures");
    await expect(kpis.agentCell("Aria", "value")).toHaveText("—");
    await expect(kpis.agentCell("Aria", "spend")).toHaveText("—");
    await expect(kpis.agentCell("Aria", "requests")).toHaveText("400");
    await expect(kpis.footnotes()).toContainText("Unable to load");
  });

  test("lists top outcomes, the write counts, and what counts as value", async () => {
    await data.kpis.interceptValue({ body: tableValue() });
    await data.kpis.interceptActivity({ body: tableActivity() });

    await kpis.goto();

    await expect(kpis.topOutcomes()).toHaveCount(2);
    await expect(kpis.topOutcomes().nth(0)).toContainText("Pull request opened");
    await expect(kpis.topOutcomes().nth(0)).toContainText("5 writes");
    await expect(kpis.topOutcomes().nth(0)).toContainText("1.7 h");
    await expect(kpis.topOutcomes().nth(0)).toContainText("$100.00");
    await expect(kpis.topOutcomes().nth(1)).toContainText("Message sent");
    await expect(kpis.footnotes()).toContainText("3 unverified writes · 2 unclassified actions");
    await expect(kpis.footnotes()).toContainText(
      "Value counts only successful aai-cli and gog write actions. The handled rate and response time cover Web Chat and Email only.",
    );
  });
});

test.describe("Organization KPIs — empty and loading states", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
  });

  test("a period with no agent work explains where the figures come from", async () => {
    await data.kpis.interceptValue({
      body: organizationValue({
        totals: valueTotals({
          successful_writes: 0,
          minutes_saved: 0,
          value: 0,
          spend: 0,
          value_to_spend_ratio: null,
          unverified_writes: 0,
          failed_writes: 0,
          unclassified_actions: 0,
        }),
        series: [{ bucket: "2026-10-01T00:00:00Z", minutes_saved: 0, value: 0, spend: 0 }],
        agents: [],
        top_outcome_types: [],
      }),
    });
    await data.kpis.interceptActivity({
      body: organizationActivity({
        totals: activityTotals({
          requests: 0,
          handled_without_failure_rate: null,
          handled_coverage: 0,
          median_response_seconds: null,
          response_time_coverage: 0,
          cost_per_request: null,
          tool_calls_per_request: null,
        }),
        requests_series: [{ bucket: "2026-10-01T00:00:00Z", requests: 0 }],
        agents: [],
      }),
    });

    await kpis.goto();

    await expect(kpis.emptyState()).toContainText(
      "Value comes from successful aai-cli and gog write actions",
    );
    await expect(kpis.emptyState()).toContainText(
      "activity comes from messages and webhook invocations",
    );
    await expect(kpis.trend()).toHaveCount(0);
    await expect(kpis.agentTable()).toHaveCount(0);
    await expect(kpis.tile("kpi-requests")).toContainText("0");
  });

  test("shows skeletons while the figures load, then the figures", async () => {
    const value = await data.kpis.interceptValue({ hold: true });
    const activity = await data.kpis.interceptActivity({ hold: true });

    await kpis.goto();

    await expect(kpis.tileSkeletons()).toHaveCount(6);
    await expect(kpis.chartSkeleton()).toBeVisible();
    await expect(kpis.tableSkeleton()).toBeVisible();
    await expect(kpis.emptyState()).toHaveCount(0);

    value.release();
    activity.release();

    await expect(kpis.tile("kpi-requests")).toContainText("480");
    await expect(kpis.tileSkeletons()).toHaveCount(0);
    await expect(kpis.chartSkeleton()).toHaveCount(0);
    await expect(kpis.tableSkeleton()).toHaveCount(0);
    await expect(kpis.agentTable()).toBeVisible();
  });
});

test.describe("Organization KPIs — value settings", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
  });

  test("shows the rate and each outcome's minutes, telling defaults from overrides", async () => {
    await data.kpis.interceptValueSettings();
    await kpis.goto();

    await kpis.openValueSettings();

    await expect(kpis.settingsSheet()).toBeVisible();
    await expect(kpis.rateInput()).toHaveValue("60");
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("20");
    await expect(kpis.outcomeRow("Pull request opened")).toContainText("Default");
    await expect(kpis.minutesInput("Message sent")).toHaveValue("8");
    await expect(kpis.outcomeRow("Message sent")).toContainText("Custom");
    await expect(kpis.settingsSheet()).toContainText(
      "Changes recalculate every figure on this page, including past periods.",
    );
    await expect(kpis.saveSettingsButton()).toBeDisabled();
  });

  test("rejects a rate or minutes the API would refuse", async () => {
    await data.kpis.interceptValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();

    await kpis.rateInput().fill("12.345");
    await expect(kpis.settingsSheet()).toContainText(
      "Enter an amount from 0 to 10,000 with at most two decimals.",
    );
    await expect(kpis.saveSettingsButton()).toBeDisabled();

    await kpis.rateInput().fill("75.50");
    await expect(kpis.saveSettingsButton()).toBeEnabled();

    await kpis.minutesInput("Pull request opened").fill("0");
    await expect(kpis.outcomeRow("Pull request opened")).toContainText(
      "Enter whole minutes from 1 to 1,440.",
    );
    await expect(kpis.saveSettingsButton()).toBeDisabled();
  });

  test("resetting an override shows the default again", async () => {
    await data.kpis.interceptValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();

    await kpis.resetToDefault("Message sent");

    await expect(kpis.minutesInput("Message sent")).toHaveValue("5");
    await expect(kpis.outcomeRow("Message sent")).toContainText("Default");
    await expect(kpis.outcomeRow("Message sent")).not.toContainText("Custom");
    await expect(kpis.saveSettingsButton()).toBeEnabled();
  });

  test("closing with unsaved edits asks first, and keeping them keeps them", async () => {
    await data.kpis.interceptValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();
    await kpis.minutesInput("Pull request opened").fill("30");

    await kpis.closeSettingsWithX();

    await expect(kpis.discardDialog()).toBeVisible();
    await kpis.keepEditing();
    await expect(kpis.discardDialog()).toHaveCount(0);
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("30");

    await kpis.pressEscape();
    await expect(kpis.discardDialog()).toBeVisible();
    await kpis.confirmDiscard();

    await expect(kpis.settingsSheet()).toHaveCount(0);
    await kpis.openValueSettings();
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("20");
  });

  test("closing without edits does not ask", async () => {
    await data.kpis.interceptValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();
    await expect(kpis.rateInput()).toHaveValue("60");

    await kpis.cancelSettings();

    await expect(kpis.settingsSheet()).toHaveCount(0);
    await expect(kpis.discardDialog()).toHaveCount(0);
  });

  test("a failed settings read shows an error with a retry", async () => {
    const settings = await data.kpis.interceptValueSettings({ status: 500 });
    await kpis.goto();
    await kpis.openValueSettings();

    await expect(kpis.settingsSheet()).toContainText("Unable to load value settings");

    settings.respondWith({ status: 200 });
    await kpis.retrySettings();

    await expect(kpis.rateInput()).toHaveValue("60");
  });
});

test.describe("Organization KPIs — saving value settings", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
  });

  test("saving an override sends only that outcome, closes, and refreshes the figures", async () => {
    const value = await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
    const settings = await data.kpis.interceptValueSettings();
    const saves = await data.kpis.interceptUpdateValueSettings({
      onSave: () => {
        const saved = valueSettings({ overrides: { MESSAGE_SENT: 7 } });
        settings.respondWith({ body: saved });
        value.respondWith({
          body: organizationValue({ totals: valueTotals({ minutes_saved: 140, value: 140 }) }),
        });
        return saved;
      },
    });
    await kpis.goto();
    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.5 h");

    await kpis.openValueSettings();
    await kpis.minutesInput("Message sent").fill("7");
    await kpis.saveSettingsButton().click();

    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0]).toEqual({ outcome_minutes: { MESSAGE_SENT: 7 } });
    await expect(kpis.settingsSheet()).toHaveCount(0);
    await expect(kpis.tile("kpi-hours-saved")).toContainText("2.3 h");
    await expect(kpis.tile("kpi-value")).toContainText("$140.00");
  });

  test("resetting an override and saving sends it back to the default", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
    await data.kpis.interceptValueSettings();
    const saves = await data.kpis.interceptUpdateValueSettings({
      onSave: () => valueSettings({ overrides: {} }),
    });
    await kpis.goto();

    await kpis.openValueSettings();
    await kpis.resetToDefault("Message sent");
    await kpis.saveSettingsButton().click();

    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0]).toEqual({ outcome_minutes: { MESSAGE_SENT: null } });
    await expect(kpis.settingsSheet()).toHaveCount(0);
  });

  test("a changed rate is sent as a number, and a cleared rate as null", async () => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
    const settings = await data.kpis.interceptValueSettings();
    const saves = await data.kpis.interceptUpdateValueSettings({
      onSave: (body) => {
        const saved = valueSettings({ hourlyRate: body.hourly_rate_usd as number | null });
        settings.respondWith({ body: saved });
        return saved;
      },
    });
    await kpis.goto();

    await kpis.openValueSettings();
    await kpis.rateInput().fill("75.5");
    await kpis.saveSettingsButton().click();
    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0]).toEqual({ hourly_rate_usd: 75.5 });
    await expect(kpis.settingsSheet()).toHaveCount(0);

    await kpis.openValueSettings();
    await expect(kpis.rateInput()).toHaveValue("75.5");
    await kpis.rateInput().fill("");
    await kpis.saveSettingsButton().click();
    await expect.poll(() => saves.length).toBe(2);
    expect(saves[1]).toEqual({ hourly_rate_usd: null });
  });

  test("a failed save keeps the panel open with the edits and says why", async ({ page }) => {
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
    await data.kpis.interceptValueSettings();
    await data.kpis.interceptUpdateValueSettings({ status: 500 });
    await kpis.goto();

    await kpis.openValueSettings();
    await kpis.minutesInput("Pull request opened").fill("30");
    await kpis.saveSettingsButton().click();

    await expect(page.getByText("Unable to save value settings")).toBeVisible();
    await expect(kpis.settingsSheet()).toBeVisible();
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("30");
  });

  test("saving refreshes value but not activity", async () => {
    const value = await data.kpis.interceptValue();
    const activity = await data.kpis.interceptActivity();
    await data.kpis.interceptValueSettings();
    await data.kpis.interceptUpdateValueSettings();
    await kpis.goto();
    await expect(kpis.tile("kpi-requests")).toContainText("480");
    const valueReadsBefore = value.requests.length;
    const activityReadsBefore = activity.requests.length;

    await kpis.openValueSettings();
    await kpis.minutesInput("Pull request opened").fill("30");
    await kpis.saveSettingsButton().click();

    await expect.poll(() => value.requests.length).toBeGreaterThan(valueReadsBefore);
    await expect(kpis.settingsSheet()).toHaveCount(0);
    expect(activity.requests.length).toBe(activityReadsBefore);
  });
});
