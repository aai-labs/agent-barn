/**
 * The advisory Update banner. It appears only when the server says a running
 * Agent's pod was built from older platform code, and its Update button runs
 * the same stop/start the Restart menu item does.
 */

import { expect, test } from "@playwright/test";

import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

test.describe("Agent update banner", () => {
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

  test("stays hidden while the Agent runs the current platform configuration", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: false },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.updateButton()).toHaveCount(0);
  });

  test("appears in the update banner when an update is available", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.updateBanner()).toBeVisible();
    await expect(agentDetailPage.updateButton()).toBeVisible();
    await expect(agentDetailPage.updateButton()).toHaveText(/update/i);
    await expect(agentDetailPage.lifecycleMenu()).toBeVisible();
  });

  test("explains that a new version is available", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.updateBanner()).toContainText(/new version.*is available/i);
  });

  test("offers a link to the release notes beside the button", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const link = agentDetailPage.updateReleasesLink();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://github.com/aai-labs/agent-barn/releases");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("the release notes link shares the button's visibility", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: false },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.updateReleasesLink()).toHaveCount(0);
  });

  test("stays hidden for a stopped Agent, which has no pod to update", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "STOPPED",
        running_model: "",
        update_available: false,
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.updateButton()).toHaveCount(0);
  });

  test("updating stops the agent and starts it again", async ({ page }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });
    await dataSupport.agents.interceptStopAgentRequest();
    await dataSupport.agents.interceptStartAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const stopped = page.waitForRequest(
      (request) =>
        request.url().endsWith(`/agents/${MOCK_AGENT_ID}/stop`) && request.method() === "POST",
    );
    const started = page.waitForRequest(
      (request) =>
        request.url().endsWith(`/agents/${MOCK_AGENT_ID}/start`) && request.method() === "POST",
    );

    await agentDetailPage.updateButton().click();

    await Promise.all([stopped, started]);
  });

  test("stays visible showing progress while the restart is still provisioning", async ({
    page,
  }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });
    await dataSupport.agents.interceptStopAgentRequest({
      body: { ...mockAgent, status: "STOPPED", running_model: "", update_available: false },
    });

    let releaseStart = () => {};
    const startHeld = new Promise<void>((resolve) => {
      releaseStart = resolve;
    });
    await page.route(`**/agents/${MOCK_AGENT_ID}/start`, async (route) => {
      await startHeld;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...mockAgent, status: "RUNNING", update_available: false }),
      });
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.updateButton().click();

    await expect(agentDetailPage.updateButton()).toBeVisible();
    await expect(agentDetailPage.updateButton()).toHaveText(/updating/i);

    releaseStart();
    await expect(agentDetailPage.updateButton()).toHaveCount(0);
  });

  test("a reader without lifecycle permission is never offered the update", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "RUNNING",
        update_available: true,
        allowed_actions: mockAgentAllowedActions.filter(
          (action) => action !== "agent.lifecycle.manage",
        ),
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.updateButton()).toHaveCount(0);
    await expect(agentDetailPage.updateReleasesLink()).toHaveCount(0);
  });
});
