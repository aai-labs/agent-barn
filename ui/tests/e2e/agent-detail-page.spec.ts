import { expect, test } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

test.describe("Agent Detail Page", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentRequest();
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
  });

  test("should load agent detail page", async () => {
    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
  });

  test("shows model name in header", async ({ page }) => {
    await expect(page.getByText("litellm/gpt-5-mini")).toBeVisible();
  });

  test("shows error state when agent fails to load", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      status: 404,
      detail: "Agent not found",
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByText("We couldn't load this agent")).toBeVisible();
    await expect(page.getByText("Agent not found")).toBeVisible();
  });

  test("should open the config drawer", async () => {
    await agentDetailPage.configureButton().click();

    await expect(agentDetailPage.configDrawerHeading()).toBeVisible();
  });

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test("should close the config drawer", async ({ page }) => {
    await agentDetailPage.configureButton().click();
    await expect(agentDetailPage.configDrawerHeading()).toBeVisible();

    await agentDetailPage.configDrawerCloseButton().click();
    await expect(agentDetailPage.configDrawerHeading()).not.toBeVisible();
  });

  test("shows Pause button when agent is RUNNING", async ({ page }) => {
    await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();
  });

  test("shows Start button when agent is STOPPED", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByRole("button", { name: /start/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /pause/i })).not.toBeVisible();
  });

  test("Pause button stops agent and updates status", async ({ page }) => {
    await dataSupportPage.agents.interceptStopAgentRequest();

    await page.getByRole("button", { name: /pause/i }).click();
    await expect(page.getByRole("button", { name: /start/i })).toBeVisible();
  });

  test("Start button starts agent and updates status", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptStartAgentRequest();
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await page.getByRole("button", { name: /start/i }).click();
    await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();
  });

  test("shows Pair button only when RUNNING", async ({ page }) => {
    await expect(page.getByRole("button", { name: /pair/i })).toBeVisible();

    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await expect(page.getByRole("button", { name: /pair/i })).not.toBeVisible();
  });

  test("Pair dialog opens and submits OAuth code", async ({ page }) => {
    await dataSupportPage.agents.interceptPairAgentRequest();

    await page.getByRole("button", { name: /pair/i }).click();
    await expect(page.getByText(`Pair Maya`)).toBeVisible();

    await page.getByPlaceholder(/enter the code/i).fill("test-oauth-code");
    await page.getByRole("button", { name: /connect/i }).click();

    await expect(page.getByText(`Pair Maya`)).not.toBeVisible();
  });
});
