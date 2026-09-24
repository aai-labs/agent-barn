import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  AGENT_A_ID,
  costRecord,
  costSummary,
  monthlyCosts,
} from "../pages/data-support/cost-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const COSTS_URL = `/dashboard/${TEST_ORG_ID}/costs`;

test.describe("Organization costs", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.costs.interceptOrgFilterOptions();
    await data.costs.interceptOrgMonthly();
  });

  test("shows monthly spend under the page's filters but not its date range", async ({
    page,
  }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });
    const monthlyRequests: URLSearchParams[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/costs/monthly")) {
        monthlyRequests.push(new URL(request.url()).searchParams);
      }
    });

    await page.goto(
      `${COSTS_URL}?agentId=${AGENT_A_ID}&from=2026-08-01T00:00:00.000Z&to=2026-08-31T00:00:00.000Z`,
    );

    const monthly = page.getByTestId("monthly-costs");
    await expect(monthly.getByRole("heading", { name: "Monthly spend" })).toBeVisible();
    await expect(page.getByTestId("monthly-current")).toContainText("$9.00");
    await expect(page.getByTestId("monthly-current")).toContainText("on pace for $30.00");
    const rows = page.getByTestId("monthly-costs-table").locator("tbody tr");
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toContainText("Sep 2026");
    // The organization table keeps its active-agents column.
    await expect(page.getByTestId("monthly-costs-table").getByRole("columnheader", { name: "Agents" })).toBeVisible();

    await expect.poll(() => monthlyRequests.at(-1)?.get("agent_id")).toBe(AGENT_A_ID);
    expect(monthlyRequests.at(-1)?.get("from_date")).toBeNull();
    expect(monthlyRequests.at(-1)?.get("to_date")).toBeNull();
  });

  test("months before the first call are left out rather than averaged as $0", async ({
    page,
  }) => {
    // Eleven empty months and then spend: the case that used to report a $0.00
    // average "over 11 full months" beside a busy current month.
    const [, , current] = monthlyCosts();
    const empty = Array.from({ length: 11 }, (_, i) => ({
      ...current,
      // October 2025 through August 2026.
      month: new Date(Date.UTC(2025, 9 + i, 1)).toISOString(),
      spend: 0,
      calls: 0,
      failed_calls: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      active_agents: 0,
      is_current: false,
      projected_spend: null,
    }));
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });
    await data.costs.interceptOrgMonthly({
      months: [...empty, { ...current, spend: 76.81, projected_spend: 100 }],
    });

    await page.goto(COSTS_URL);

    await expect(page.getByTestId("monthly-current")).toContainText("$76.81");
    await expect(page.getByTestId("monthly-average")).toContainText("—");
    await expect(page.getByTestId("monthly-average")).toContainText("no full month yet");
    await expect(page.getByTestId("monthly-total")).toContainText("1 month");
    await expect(page.getByTestId("monthly-costs-table").locator("tbody tr")).toHaveCount(1);
    // There was no last month to speak of, so it is not reported as a $0 one.
    await expect(page.getByTestId("monthly-previous")).toContainText("—");
    await expect(page.getByTestId("monthly-previous")).not.toContainText("$0.00");
  });

  test("a quiet month after the first call still counts toward the average", async ({ page }) => {
    const [july, august, september] = monthlyCosts();
    const quiet = { spend: 0, calls: 0, failed_calls: 0, prompt_tokens: 0, completion_tokens: 0 };
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });
    await data.costs.interceptOrgMonthly({
      months: [
        { ...july, month: "2026-06-01T00:00:00Z", ...quiet },
        july,
        { ...august, ...quiet },
        september,
      ],
    });

    await page.goto(COSTS_URL);

    // June is before the first call and drops out; August is a real quiet month.
    await expect(page.getByTestId("monthly-costs-table").locator("tbody tr")).toHaveCount(3);
    await expect(page.getByTestId("monthly-average")).toContainText("$5.00");
    await expect(page.getByTestId("monthly-average")).toContainText("over 2 full months");
    // August is inside the history, so a $0 last month is the real figure.
    await expect(page.getByTestId("monthly-previous")).toContainText("$0.00");
    await expect(page.getByTestId("monthly-previous")).toContainText("Aug 2026");
  });

  test("an error in the monthly totals stays inside its section", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });
    await data.costs.interceptOrgMonthly({ status: 500 });

    await page.goto(COSTS_URL);

    await expect(page.getByText("Unable to load monthly spend")).toBeVisible();
    await expect(page.getByTestId("cost-total-spend")).toContainText("$143.03");
  });

  test("renders the summary cards and the calls table", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });

    await page.goto(COSTS_URL);

    await expect(page.getByRole("heading", { name: "Costs" })).toBeVisible();
    await expect(page.getByTestId("cost-total-spend")).toContainText("$143.03");
    await expect(page.getByTestId("cost-active-agents")).toContainText("3");
    await expect(page.getByTestId("cost-top-model")).toContainText("claude-opus-5");
    await expect(page.getByTestId("cost-list")).toBeVisible();
    await expect(page.getByTestId("cost-row")).toHaveCount(1);
    await expect(page.getByText("glm-5.2")).toBeVisible();
  });

  test("a legend of long agent names stays inside its card", async ({ page }) => {
    const names = [
      "Aria the Research Assistant",
      "Meticulous Documentation Bot",
      "Quarterly Reporting Analyst",
      "Customer Escalation Handler",
      "Infrastructure Cost Auditor",
      "Onboarding Concierge Agent",
    ];
    const series = names.flatMap((agent_name, i) =>
      ["2026-08-04", "2026-08-05", "2026-08-06"].map((day, j) => ({
        bucket: `${day}T00:00:00Z`,
        agent_id: `0000000${i}-0000-4000-8000-00000000000${i}`,
        agent_name,
        spend: 1 + i * 0.7 + j * 0.3,
      })),
    );

    await data.costs.interceptOrgSummary({
      summary: { ...costSummary(), spend_by_agent_over_time: series },
    });
    await data.costs.interceptOrgList({ items: [], total: 0 });

    await page.goto(COSTS_URL);

    const card = page.getByTestId("spend-by-agent-card");
    await expect(card).toBeVisible();
    const cardBox = (await card.boundingBox())!;

    // Each entry, not the flex container around them: the container is sized by its
    // parent and stays put while its children run off both edges, which is the
    // failure being guarded. Measuring the container passes on the broken layout.
    const entries = card.locator(".recharts-legend-wrapper > div > div");
    await expect(entries).toHaveCount(names.length);

    for (let i = 0; i < names.length; i += 1) {
      const entry = entries.nth(i);
      await expect(entry).toHaveText(new RegExp(names[i]));
      const box = (await entry.boundingBox())!;
      expect(box.x, `"${names[i]}" starts left of the card`).toBeGreaterThanOrEqual(
        cardBox.x,
      );
      expect(
        box.x + box.width,
        `"${names[i]}" runs past the right of the card`,
      ).toBeLessThanOrEqual(cardBox.x + cardBox.width);
    }
  });

  test("cost-per-call ticks avoid glyphs the page font cannot draw", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [], total: 0 });

    await page.goto(COSTS_URL);

    // Geist has no glyph at U+2264, so a "≤" here was drawn in a fallback face and
    // the whole axis read as a different font.
    const ticks = page.getByTestId("cost-per-call-card").locator(".recharts-cartesian-axis-tick-value");
    await expect(ticks.first()).toBeVisible();
    for (const text of await ticks.allTextContents()) {
      expect(text).not.toMatch(/[\u2264\u2265]/);
    }
  });

  test("a filter lands in the URL and narrows the request", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });

    await page.goto(COSTS_URL);
    await expect(page.getByTestId("cost-list")).toBeVisible();

    const listRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/costs?") &&
        request.url().includes(`agent_id=${AGENT_A_ID}`),
    );

    await page.getByTestId("cost-agent-filter").click();
    await page.getByRole("option", { name: "Aria" }).click();

    await listRequest;
    await expect(page).toHaveURL(new RegExp(`agentId=${AGENT_A_ID}`));
  });

  test("a chosen date range lands in the URL and bounds the request", async ({
    page,
  }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });

    await page.goto(COSTS_URL);
    await expect(page.getByTestId("cost-list")).toBeVisible();

    // Both bounds have to reach the server together. They are written in one
    // update, so a half-applied range would show up here as a missing param.
    const boundedRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/costs?") &&
        request.url().includes("from_date=") &&
        request.url().includes("to_date="),
    );

    await page.getByLabel("Date range").click();
    // Two days in the same month, so the range closes without paging.
    const days = page.getByRole("gridcell").filter({ hasText: /^\d+$/ });
    await days.nth(4).click();
    await days.nth(9).click();

    await boundedRequest;
    await expect(page).toHaveURL(/from=/);
    await expect(page).toHaveURL(/to=/);
  });

  test("a filter survives a reload, because it lives in the URL", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });

    await page.goto(`${COSTS_URL}?model=openrouter%2Fz-ai%2Fglm-5.2`);

    await expect(page.getByTestId("cost-model-filter")).toContainText("glm-5.2");
  });

  test("scrolling to the end loads the next page without repeating a row", async ({
    page,
  }) => {
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      costRecord({
        request_id: `gen-page1-${String(index).padStart(4, "0")}`,
        model: `openrouter/test/model-${index}`,
      }),
    );
    const secondPage = [
      costRecord({ request_id: "gen-page2-0000", model: "openrouter/test/model-50" }),
    ];
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({
      pages: [firstPage, secondPage],
      total: 51,
    });

    await page.goto(COSTS_URL);
    await expect(page.getByTestId("cost-list")).toBeVisible();

    await page.mouse.wheel(0, 40000);

    await expect(page.getByText("model-50")).toBeVisible();
    // A repeated request id would collide as a React key; the merge dedupes on it.
    const rendered = await page.getByTestId("cost-row").count();
    expect(rendered).toBeLessThanOrEqual(51);
  });

  test("an empty period explains where cost records come from", async ({ page }) => {
    await data.costs.interceptOrgSummary({
      summary: costSummary({
        total_spend: 0,
        total_calls: 0,
        active_agents: 0,
        top_model: null,
        spend_over_time: [],
        spend_by_agent_over_time: [],
        avg_prompt_tokens_over_time: [],
        cost_per_call_histogram: [],
      }),
    });
    await data.costs.interceptOrgList({ items: [], total: 0 });

    await page.goto(COSTS_URL);

    await expect(page.getByTestId("cost-list-empty")).toContainText(
      "No LLM calls recorded in this period",
    );
    await expect(page.getByTestId("cost-list-empty")).toContainText(
      "every 15 minutes",
    );
  });

  test("a failed list shows an error state with a retry", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ status: 500 });

    await page.goto(COSTS_URL);

    await expect(page.getByText("Unable to load costs")).toBeVisible();
  });
});

test.describe("Organization costs — agents by spend", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  const AGENT_ROWS = [
    {
      agent_id: "11111111-1111-4111-8111-111111111111",
      agent_name: "Zeta",
      spend: 1.0,
      calls: 40,
      prompt_tokens: 100,
      completion_tokens: 50,
    },
    {
      agent_id: "22222222-2222-4222-8222-222222222222",
      agent_name: "Alpha",
      spend: 5.0,
      calls: 10,
      prompt_tokens: 900,
      completion_tokens: 100,
    },
  ];

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.costs.interceptOrgFilterOptions();
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [costRecord()], total: 1 });

    await page.route("**/costs/agents?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(AGENT_ROWS),
      });
    });
  });

  const agentColumn = (page: import("@playwright/test").Page) =>
    page
      .getByTestId("agents-by-spend")
      .locator("tbody tr td:first-child")
      .allInnerTexts();

  // Scoped to the table: "Agent" alone also matches the "Hire agent" button in the nav.
  const sortBy = (page: import("@playwright/test").Page, column: string) =>
    page.getByTestId("agents-by-spend").getByRole("button", { name: column }).click();

  test("ranks agents by spend by default", async ({ page }) => {
    await page.goto(COSTS_URL);

    await expect(page.getByTestId("agents-by-spend")).toBeVisible();
    expect(await agentColumn(page)).toEqual(["Alpha", "Zeta"]);
  });

  test("sorts by a column and reverses on a second click", async ({ page }) => {
    await page.goto(COSTS_URL);
    await expect(page.getByTestId("agents-by-spend")).toBeVisible();

    // Calls order is the inverse of spend order, so this cannot pass by accident.
    await sortBy(page, "Calls");
    expect(await agentColumn(page)).toEqual(["Zeta", "Alpha"]);

    await sortBy(page, "Calls");
    expect(await agentColumn(page)).toEqual(["Alpha", "Zeta"]);
  });

  test("sorts the agent name alphabetically", async ({ page }) => {
    await page.goto(COSTS_URL);
    await expect(page.getByTestId("agents-by-spend")).toBeVisible();

    await sortBy(page, "Agent");

    expect(await agentColumn(page)).toEqual(["Alpha", "Zeta"]);
    await expect(
      page.getByTestId("agents-by-spend").getByRole("columnheader", { name: "Agent" }),
    ).toHaveAttribute("aria-sort", "ascending");
  });

  test("selecting a row filters the page to that agent and keeps the table whole", async ({
    page,
  }) => {
    await page.goto(COSTS_URL);
    await expect(page.getByTestId("agents-by-spend")).toBeVisible();

    await page.getByRole("cell", { name: "Alpha", exact: true }).click();

    await expect(page).toHaveURL(/agentId=22222222-2222-4222-8222-222222222222/);
    // The table drops the agent dimension, so it must still list every agent —
    // otherwise picking a row would collapse it to the row just picked.
    expect(await agentColumn(page)).toEqual(["Alpha", "Zeta"]);
  });
});
