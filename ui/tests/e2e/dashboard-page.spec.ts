import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import { agentListWithMetadata, agentListWithoutMetadata, agentListWithPollingStates } from "../fixtures/agent-list";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { TEST_ORG_ID } from "../constants";

test.describe("Dashboard Page", () => {
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.organizations.interceptGetOrganizationLlmBudget();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
  });

  test("should load dashboard with agent cards", async ({ page }) => {
    await dashboardPage.goto();

    await expect(dashboardPage.heading()).toBeVisible();
    await expect(page.getByText("Maya")).toBeVisible();
  });

  test("shows running and idle counts", async ({ page }) => {
    await dashboardPage.goto();

    await expect(page.getByText(/working now/)).toBeVisible();
  });

  test("polls permitted running cards every 30 seconds and skips restricted or stopped cards", async ({ page }) => {
    await page.clock.install();
    await dataSupportPage.agents.interceptGetAgentsRequest({ body: agentListWithPollingStates });
    const requests = await Promise.all(agentListWithPollingStates.items.map((agent) =>
      dataSupportPage.agents.interceptGetAgentHealthRequest({ agentId: agent.id }),
    ));
    await dashboardPage.goto();
    await expect.poll(() => requests[0].count).toBe(1);
    await expect(dashboardPage.agentCard("Read-only metadata")).toBeVisible();
    await expect(dashboardPage.agentCard("Read-only metadata").getByText("Running", { exact: true })).toBeVisible();
    await page.clock.runFor(29_000);
    expect(requests.map((request) => request.count)).toEqual([1, 0, 0]);
    await page.clock.runFor(1_000);
    await expect.poll(() => requests[0].count).toBe(2);
    expect(requests.map((request) => request.count)).toEqual([2, 0, 0]);
  });

  test("shows creator and exact last-message time directly on the card", async () => {
    await dashboardPage.goto();
    const card = dashboardPage.agentCard("Maya");
    await expect(card.getByText("By Tommy", { exact: true })).toBeVisible();
    await expect(card.getByText("Last message", { exact: true })).toBeVisible();
    await expect(dashboardPage.lastMessageTime("Maya")).toHaveAttribute("datetime", mockAgent.last_message_at);
    await expect(card.getByRole("button")).toHaveCount(0);
    await expect(card).toHaveAccessibleDescription(/Working By Tommy Last message/);
  });

  test("does not mistake an older API's missing metadata for an empty history", async () => {
    await dataSupportPage.agents.interceptGetAgentsRequest({ body: agentListWithoutMetadata });
    await dashboardPage.goto();
    await expect(dashboardPage.agentCard("Maya").getByText("Creator not recorded", { exact: true })).toBeVisible();
    await expect(dashboardPage.agentCard("Maya").getByText("Not available", { exact: true })).toBeVisible();
  });

  for (const keyboard of [false, true]) {
    test(`hire card opens the hiring dialog with ${keyboard ? "Enter" : "a click"}`, async () => {
      await dataSupportPage.agents.interceptGetTemplatesRequest();
      await dataSupportPage.agents.interceptGetModelsRequest();
      await dataSupportPage.agents.interceptNameSuggestionRequest();
      await dashboardPage.goto();
      await expect(dashboardPage.hireCard()).toHaveCount(1);
      await dashboardPage.openHireCard(keyboard);
      await expect(dashboardPage.agentNameInput()).toBeVisible();
      await dashboardPage.closeHireDialog();
      await expect(dashboardPage.hireCard()).toBeVisible();
    });

    test(`whole-card navigation works with ${keyboard ? "Enter" : "a click"}`, async ({ page }) => {
      await dataSupportPage.agents.interceptGetAgentRequest();
      await dataSupportPage.agents.interceptGetAgentTemplateRequest();
      await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
      await dashboardPage.goto();
      await dashboardPage.openAgent("Maya", keyboard);
      await expect(page).toHaveURL(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}`);
    });
  }

  for (const width of [360, 1100]) {
    test(`footers stay at the bottom with wrapping content at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await dataSupportPage.agents.interceptGetAgentsRequest({ body: agentListWithMetadata });
      await dashboardPage.goto();
      const legacy = dashboardPage.agentCard("Karl the Assistant with a longer name");
      await expect(legacy.getByText("Creator not recorded", { exact: true })).toBeVisible();
      await expect(legacy.getByText("No messages yet", { exact: true })).toBeVisible();
      const restricted = dashboardPage.agentCard("Read-only metadata");
      await expect(restricted.getByText("Not available", { exact: true })).toBeVisible();
      await expect(restricted.getByText("By tommy@example.com", { exact: true })).toBeVisible();
      for (const name of agentListWithMetadata.items.map((agent) => agent.name)) {
        expect(await dashboardPage.cardFooterBottomGap(name)).toBeLessThanOrEqual(1);
      }
      await page.screenshot({ path: testInfo.outputPath("team-cards.png"), fullPage: true });
    });
  }

  test("search filters displayed teammates and offers a clear empty state", async () => {
    await dataSupportPage.agents.interceptGetAgentsRequest({ body: agentListWithMetadata });
    await dashboardPage.goto();
    await dashboardPage.searchTeammates("Karl");
    await expect(dashboardPage.agentCard("Maya")).toHaveCount(0);
    await expect(dashboardPage.agentCard("Karl the Assistant with a longer name")).toBeVisible();
    await dashboardPage.searchTeammates("no-such-agent");
    await expect(dashboardPage.agentCard("Karl the Assistant with a longer name")).toHaveCount(0);
    await expect(dashboardPage.hireCard()).toBeVisible();
    await dashboardPage.searchTeammates("");
    await expect(dashboardPage.agentCard("Maya")).toBeVisible();
  });

  test("explains the loaded-page search limit when more teammates exist", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentsRequest({
      body: { ...agentListWithMetadata, total: 51 },
    });
    await dashboardPage.goto();

    await expect(page.getByText("Showing 3 of 51 teammates. Search applies to the teammates shown.", { exact: true })).toBeVisible();
    await dashboardPage.searchTeammates("Karl");
    await expect(dashboardPage.agentCard("Maya")).toHaveCount(0);
    await expect(dashboardPage.agentCard("Karl the Assistant with a longer name")).toBeVisible();
    await expect(page.getByText("Showing 3 of 51 teammates. Search applies to the teammates shown.", { exact: true })).toBeVisible();
  });

  test("shows empty state when no agents", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentsRequest({
      body: { page: 1, page_size: 50, total: 0, items: [] },
    });

    await dashboardPage.goto();

    await expect(page.getByText("No agents yet")).toBeVisible();
    await expect(dashboardPage.hireCard()).toBeVisible();
  });

  test("shows error state when agents fail to load", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentsRequest({
      status: 500,
      detail: "Agents service unavailable",
    });

    await dashboardPage.goto();

    await expect(page.getByText("We couldn't load your agents")).toBeVisible();
    await expect(page.getByText("Agents service unavailable")).toBeVisible();
  });

  test("shows an account error state when user context fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetUserContextRequest({
      status: 500,
      detail: "Account service unavailable",
    });

    await dashboardPage.goto();

    await expect(
      page.getByText("We couldn't load your account"),
    ).toBeVisible();
    await expect(
      page.getByText("Account service unavailable"),
    ).toBeVisible();
  });

  test("shows an inline error state when a later users search fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetUsersRequest({
      status: 500,
      detail: "Users service unavailable",
      failAfterRequests: 1,
    });

    await dashboardPage.gotoUsers();
    await dashboardPage.searchInput("Search users").fill("ada");

    await expect(
      page.getByText("We couldn't load users"),
    ).toBeVisible();
    await expect(page.getByText("Users service unavailable")).toBeVisible();
  });

  test("shows an inline error state when a later organizations search fails", async ({
    page,
  }) => {
    await dataSupportPage.users.interceptGetOrganizationsRequest({
      status: 500,
      detail: "Organizations service unavailable",
      failAfterRequests: 1,
    });

    await dashboardPage.gotoOrganizations();
    await dashboardPage.searchInput("Search organizations").fill("aai");

    await expect(
      page.getByText("We couldn't load organizations"),
    ).toBeVisible();
    await expect(
      page.getByText("Organizations service unavailable"),
    ).toBeVisible();
  });
});
