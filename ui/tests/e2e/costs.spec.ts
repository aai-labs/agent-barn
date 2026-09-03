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

  test("a recovered cost is marked, so a rising total is explainable", async ({
    page,
  }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({
      items: [costRecord({ healed: true })],
      total: 1,
    });

    await page.goto(COSTS_URL);

    await expect(
      page.getByLabel("Cost recovered from OpenRouter"),
    ).toBeVisible();
  });

  test("a failed list shows an error state with a retry", async ({ page }) => {
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ status: 500 });

    await page.goto(COSTS_URL);

    await expect(page.getByText("Unable to load costs")).toBeVisible();
  });
});
