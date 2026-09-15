import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  AGENT_A_ID,
  costRecord,
  costSummary,
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
