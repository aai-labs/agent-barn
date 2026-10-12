/**
 * The pending-model banner. It appears on the Agent detail page when a running
 * Agent started on a different model than the one that resolves now, and offers
 * a restart to lifecycle managers.
 */

import { expect, test } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

const pendingAgent = { ...mockAgent, status: "RUNNING", pending_model: "litellm/gpt-5" };

test.describe("Agent pending-model banner", () => {
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

  test("stays hidden when the Agent runs the model that resolves now", async () => {
    await dataSupport.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "RUNNING" } });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.pendingModelBanner()).toHaveCount(0);
  });

  test("names the running and pending models and offers a restart", async () => {
    await dataSupport.agents.interceptGetAgentRequest({ body: pendingAgent });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await expect(agentDetailPage.pendingModelBanner()).toContainText(
      "Maya is still running on litellm/gpt-5-mini. Restart it to switch to litellm/gpt-5.",
    );
    await expect(agentDetailPage.pendingModelRestartButton()).toBeEnabled();
  });

  test("hides the restart action without lifecycle permission", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...pendingAgent, allowed_actions: mockAgentAllowedActions.filter((a) => a !== "agent.lifecycle.manage") },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await expect(agentDetailPage.pendingModelBanner()).toBeVisible();
    await expect(agentDetailPage.pendingModelRestartButton()).toHaveCount(0);
  });
});
