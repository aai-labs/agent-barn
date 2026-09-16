/**
 * The header control that starts, pauses and restarts an Agent. The button runs the
 * action the Agent's state calls for; the menu keeps all three reachable.
 */

import { expect, test } from "@playwright/test";

import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

test.describe("Agent lifecycle menu", () => {
  let agentDetailPage: AgentDetailPage;
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentTemplateRequest();
    await dataSupport.agents.interceptGetConversationChannelsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetModelsRequest();
    await dataSupport.agents.interceptGetAgentHealthRequest();
  });

  test("offers Pause on the button and Restart in the menu while running", async ({ page }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING" },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
    await agentDetailPage.lifecycleMenuTrigger().click();
    await expect(page.getByRole("menuitem", { name: "Pause", exact: true })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Restart", exact: true })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Start", exact: true })).toHaveCount(0);
  });

  test("offers Start alone, with no menu, while stopped", async ({ page }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", running_model: "" },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByRole("button", { name: "Start", exact: true })).toBeVisible();
    await expect(agentDetailPage.lifecycleMenuTrigger()).toHaveCount(0);
  });

  test("restart stops the agent and starts it again", async ({ page }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING" },
    });
    await dataSupport.agents.interceptStopAgentRequest();
    await dataSupport.agents.interceptStartAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const stopped = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/stop`) && request.method() === "POST",
    );
    const started = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/start`) && request.method() === "POST",
    );

    await agentDetailPage.lifecycleMenuTrigger().click();
    await page.getByRole("menuitem", { name: "Restart", exact: true }).click();

    await Promise.all([stopped, started]);
  });

  test("a reader without lifecycle permission gets no control at all", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "RUNNING",
        allowed_actions: mockAgentAllowedActions.filter(
          (action) => action !== "agent.lifecycle.manage",
        ),
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.lifecycleMenu()).toHaveCount(0);
  });
});
