import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { AgentDetailPage } from "../pages/agent-detail-page.po";
import { AgentsOverviewPage } from "../pages/agents-overview-page.po";
import { MOCK_AGENT_ID } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  MOCK_SECOND_AGENT_ID,
  mockAgentOverview,
  mockOverviewItem,
  mockUsageSnapshot,
} from "../pages/data-support/resource-usage-data-support.po";

const ADA = mockOverviewItem({
  id: MOCK_SECOND_AGENT_ID,
  name: "Ada",
  spend: { spend: 30.25, calls: 900, last_call_at: null },
  resource_usage: mockUsageSnapshot({ memory_working_set_bytes: 805_306_368, cpu_cores: 0.4 }),
});

test.describe("Agents overview", () => {
  let overview: AgentsOverviewPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    overview = new AgentsOverviewPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    for (const agentId of [MOCK_AGENT_ID, MOCK_SECOND_AGENT_ID]) {
      await dataSupportPage.agents.interceptGetAgentHealthRequest({ agentId });
      await dataSupportPage.costs.interceptAgentCosts(agentId);
      await dataSupportPage.resourceUsage.interceptAgentResourceUsage(agentId);
    }
    await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest();
    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem(), ADA]),
    });
  });

  test("lists every agent, biggest spend first", async () => {
    await overview.goto();

    await expect(overview.rows()).toHaveCount(2);
    expect(await overview.names()).toEqual(["Ada", "Maya"]);
    await expect(overview.row("Ada").getByTestId("agents-overview-spend")).toContainText("$30.25");
    await expect(overview.row("Ada").getByTestId("agents-overview-spend")).toContainText("900 calls");
    await expect(overview.row("Maya").getByTestId("agents-overview-spend")).toContainText("$12.50");
  });

  test("shows status, CPU and memory against limits in the row", async () => {
    await overview.goto();

    const maya = overview.row("Maya");
    await expect(maya).toContainText("Working");
    await expect(maya.getByTestId("agents-overview-cpu")).toContainText("0.05 / 0.5 cores");
    await expect(maya.getByTestId("agents-overview-memory")).toContainText("342 MiB / 1 GiB");
    await expect(maya.getByRole("meter")).toHaveCount(2);
  });

  test("re-sorts by any column and says which way", async ({ page }) => {
    await overview.goto();
    await expect(overview.rows()).toHaveCount(2);
    const agentHeader = page.getByRole("columnheader", { name: "Agent", exact: true });

    await overview.sortButton("name").click();
    expect(await overview.names()).toEqual(["Ada", "Maya"]);
    await expect(agentHeader).toHaveAttribute("aria-sort", "ascending");

    await overview.sortButton("name").click();
    expect(await overview.names()).toEqual(["Maya", "Ada"]);
    await expect(agentHeader).toHaveAttribute("aria-sort", "descending");

    await overview.sortButton("spend").click();
    expect(await overview.names()).toEqual(["Ada", "Maya"]);

    await overview.sortButton("memory").click();
    // Ada uses 75% of its memory, Maya 33%.
    expect(await overview.names()).toEqual(["Ada", "Maya"]);
    await overview.sortButton("memory").click();
    expect(await overview.names()).toEqual(["Maya", "Ada"]);
  });

  test("marks an agent that CPU-throttling is holding back", async () => {
    const throttled = mockOverviewItem({
      resource_usage: mockUsageSnapshot({ cpu_throttled_ratio: 0.4 }),
    });
    await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([throttled]) });
    await overview.goto();

    const marker = overview.row("Maya").getByTestId("agents-overview-throttled");
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute("aria-label", "Throttled 40% of the last hour");
  });

  test("does not mark an agent that is not being held back", async () => {
    await overview.goto();

    await expect(overview.row("Maya")).toBeVisible();
    await expect(overview.row("Maya").getByTestId("agents-overview-throttled")).toHaveCount(0);
  });

  test("keeps an agent visible when the reader may not see its figures", async () => {
    const locked = mockOverviewItem({
      id: MOCK_SECOND_AGENT_ID,
      name: "Locked",
      allowed_actions: ["agent.read"],
      spend: null,
      resource_usage: null,
    });
    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem(), locked]),
    });
    await overview.goto();

    await expect(overview.rows()).toHaveCount(2);
    const row = overview.row("Locked");
    await expect(row.getByTestId("agents-overview-spend")).toHaveCount(0);
    await expect(row.getByTitle("You don't have access to this agent's cost")).toBeVisible();
    await expect(row.getByTitle("You don't have access to this agent's resource usage")).toHaveCount(2);
    // A row with nothing to compare sorts last, whichever way the column runs.
    expect(await overview.names()).toEqual(["Maya", "Locked"]);
    await overview.sortButton("spend").click();
    expect(await overview.names()).toEqual(["Maya", "Locked"]);
  });

  test("shows a stopped agent without pretending to measure it", async () => {
    const stopped = mockOverviewItem({ name: "Sleepy", status: "STOPPED", resource_usage: null });
    await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([stopped]) });
    await overview.goto();

    const row = overview.row("Sleepy");
    await expect(row).toContainText("Idle");
    await expect(row.getByTitle("Stopped")).toHaveCount(2);
  });

  test("tells an agent on an older helper to restart", async () => {
    const stale = mockOverviewItem({
      resource_usage: mockUsageSnapshot({
        state: "restart_required",
        memory_working_set_bytes: null,
        memory_limit_bytes: null,
        cpu_cores: null,
        cpu_limit_cores: null,
        cpu_throttled_ratio: null,
      }),
    });
    await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([stale]) });
    await overview.goto();

    await expect(overview.row("Maya").getByText("Restart to report")).toHaveCount(2);
  });

  test("keeps spend and status when the usage source cannot be reached", async ({ page }) => {
    const noUsage = mockOverviewItem({ resource_usage: null });
    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([noUsage], { resource_usage_availability: "unavailable" }),
    });
    await overview.goto();

    await expect(page.getByTestId("resource-usage-notice")).toContainText("unavailable right now");
    await expect(overview.row("Maya").getByTestId("agents-overview-spend")).toContainText("$12.50");
    await expect(overview.row("Maya")).toContainText("Working");
  });

  test("says when monitoring is not set up, without offering a retry", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem({ resource_usage: null })], {
        resource_usage_availability: "not_configured",
      }),
    });
    await overview.goto();

    await expect(page.getByTestId("resource-usage-notice")).toContainText("isn't set up here");
    await expect(page.getByTestId("resource-usage-notice").getByRole("button")).toHaveCount(0);
  });

  test("totals spend over the period the reader picks", async ({ page }) => {
    const requests = await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem()]),
    });
    await overview.goto();
    await expect(overview.rows()).toHaveCount(1);
    expect(requests.map((request) => request.get("period"))).toEqual(["THIRTY_DAYS"]);

    await overview.choosePeriod("Last 7 days");

    await expect.poll(() => requests.map((request) => request.get("period"))).toContain("SEVEN_DAYS");
    await expect(page).toHaveURL(/period=SEVEN_DAYS/);
  });

  test("says how many agents it is showing when there are more", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem()], { total: 140 }),
    });
    await overview.goto();

    await expect(page.getByText("Showing 1 of 140 agents.")).toBeVisible();
  });

  test("has a friendly empty state", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([]) });
    await overview.goto();

    await expect(page.getByTestId("agents-overview-empty")).toContainText("No agents yet");
    await expect(overview.rows()).toHaveCount(0);
  });

  test("reports a failed request and retries it", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentOverview({ status: 500 });
    await overview.goto();
    await expect(page.getByText("We couldn't load your agents")).toBeVisible();

    await dataSupportPage.resourceUsage.interceptAgentOverview({
      body: mockAgentOverview([mockOverviewItem()]),
    });
    await page.getByRole("button", { name: "Retry" }).click();

    await expect(overview.row("Maya")).toBeVisible();
  });

  test.describe("opening a row", () => {
    test("shows status, cost and resource usage, each linking to its own tab", async ({ page }) => {
      await overview.goto();
      const toggle = overview.toggleFor("Maya");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(overview.details()).toHaveCount(0);

      await toggle.click();

      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(overview.details()).toBeVisible();
      const status = page.getByTestId("agent-overview-status");
      await expect(status).toContainText("Model");
      await expect(status).toContainText("gpt-5-mini");
      const cost = page.getByTestId("agent-overview-cost");
      await expect(cost).toContainText("$12.50");
      await expect(cost).toContainText("8");
      const usage = page.getByTestId("agent-overview-usage");
      await expect(usage).toContainText("342 MiB of 1 GiB");
      await expect(usage).toContainText("Peak memory, 24h");

      await expect(status.getByRole("link", { name: /Open agent/ })).toHaveAttribute(
        "href",
        `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}`,
      );
      await expect(cost.getByRole("link", { name: /See costs/ })).toHaveAttribute("href", /tab=costs$/);
      await expect(usage.getByRole("link", { name: /See resource usage/ })).toHaveAttribute(
        "href",
        /tab=resource-usage$/,
      );
    });

    test("shows the same spend in the row and in its cost panel", async ({ page }) => {
      await overview.goto();
      const rowSpend = await overview.row("Maya").getByTestId("agents-overview-spend").innerText();

      await overview.toggleFor("Maya").click();

      await expect(page.getByTestId("agent-overview-cost")).toContainText(rowSpend.split("\n")[0]);
    });

    test("collapses again", async () => {
      await overview.goto();
      await overview.toggleFor("Maya").click();
      await expect(overview.details()).toBeVisible();

      await overview.row("Maya").click();

      await expect(overview.details()).toHaveCount(0);
    });

    test("opens only the row that was chosen", async () => {
      await overview.goto();

      await overview.toggleFor("Ada").click();

      await expect(overview.details()).toHaveCount(1);
      await expect(overview.toggleFor("Maya")).toHaveAttribute("aria-expanded", "false");
    });

    test("explains a panel the reader may not open", async ({ page }) => {
      const noCost = mockOverviewItem({
        allowed_actions: ["agent.read", "activity.read"],
        spend: null,
      });
      await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([noCost]) });
      await overview.goto();

      await overview.toggleFor("Maya").click();

      await expect(page.getByTestId("agent-overview-cost")).toContainText("don't have access to this agent's cost");
      await expect(page.getByTestId("agent-overview-usage")).toContainText("342 MiB of 1 GiB");
    });

    test("does not ask for resource usage of a stopped agent", async ({ page }) => {
      const requests = await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID);
      const stopped = mockOverviewItem({ status: "STOPPED", resource_usage: null });
      await dataSupportPage.resourceUsage.interceptAgentOverview({ body: mockAgentOverview([stopped]) });
      await overview.goto();

      await overview.toggleFor("Maya").click();

      await expect(page.getByTestId("agent-overview-usage")).toContainText("Stopped");
      expect(requests).toEqual([]);
    });
  });

  test.describe("navigation", () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test("marks Usage, not Home, on the overview", async () => {
      await overview.goto();

      await expect(overview.heading()).toBeVisible();
      await expect(overview.navLink("Usage")).toHaveAttribute("aria-current", "page");
      await expect(overview.navLink("Home")).not.toHaveAttribute("aria-current", "page");
    });

    test("marks Home, not Usage, on the organization's home and on an agent's page", async ({ page }) => {
      await page.goto(`/dashboard/${TEST_ORG_ID}`);

      await expect(overview.navLink("Home")).toHaveAttribute("aria-current", "page");
      await expect(overview.navLink("Usage")).not.toHaveAttribute("aria-current", "page");

      // An agent's back link says "Your team" and leads Home, so Home is the tab it sits under.
      await dataSupportPage.agents.interceptGetAgentRequest();
      await new AgentDetailPage(page).goto(MOCK_AGENT_ID);

      await expect(overview.navLink("Home")).toHaveAttribute("aria-current", "page");
      await expect(overview.navLink("Usage")).not.toHaveAttribute("aria-current", "page");
    });

    test("shows a plain member the Usage page but not Costs", async () => {
      await dataSupportPage.users.interceptGetUserContextRequest({
        userContext: {
          ...UserContext,
          is_platform_admin: false,
          organization_users: [{ ...UserContext.organization_users[0], role: "MEMBER" }],
        },
      });
      await overview.goto();

      await expect(overview.navLink("Usage")).toBeVisible();
      await expect(overview.navLink("Costs")).toHaveCount(0);
      await expect(overview.rows()).toHaveCount(2);
    });
  });
});
