/**
 * The Update banner. It appears when the server says a running Agent's pod was
 * built from older platform code. Its button asks the server for a managed
 * update; the server's updateInProgress flag then keeps it busy until the
 * update ends, and a note says how it ended when that was not a success.
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

  test("updating asks the server to run the managed update", async ({ page }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", update_available: true },
    });
    await page.route(`**/agents/${MOCK_AGENT_ID}/managed-update`, async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ ...mockAgent, status: "RUNNING", update_available: true }),
      });
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const requested = page.waitForRequest(
      (request) =>
        request.url().endsWith(`/agents/${MOCK_AGENT_ID}/managed-update`) &&
        request.method() === "POST",
    );

    await agentDetailPage.updateButton().click();

    await requested;
  });

  test("stays busy while the server runs the update, then goes away once it succeeds", async ({
    page,
  }) => {
    let current: Record<string, unknown> = { ...mockAgent, status: "RUNNING", update_available: true };
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
    });
    await page.route(`**/agents/${MOCK_AGENT_ID}/managed-update`, async (route) => {
      current = { ...mockAgent, status: "STOPPED", running_model: "", update_in_progress: true };
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ ...mockAgent, status: "RUNNING", update_available: true, update_in_progress: true }),
      });
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.updateButton().click();

    // Still offered as "available" in the 202, but it cannot be clicked twice.
    await expect(agentDetailPage.updateButton()).toHaveText(/updating/i);
    await expect(agentDetailPage.updateButton()).toBeDisabled();

    current = {
      ...mockAgent,
      status: "RUNNING",
      update_available: false,
      update_in_progress: false,
      last_managed_update: { outcome: "SUCCEEDED", restore_point_id: null, failure_reason: null },
    };
    await expect(agentDetailPage.updateButton()).toHaveCount(0, { timeout: 15_000 });
    await expect(agentDetailPage.updateOutcome()).toHaveCount(0);
  });

  test("after a rollback, offers the update again and says why", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "RUNNING",
        update_available: true,
        last_managed_update: { outcome: "ROLLED_BACK", restore_point_id: null, failure_reason: null },
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.updateButton()).toBeEnabled();
    await expect(agentDetailPage.updateOutcome()).toContainText(/rolled back/i);
  });

  test("when the backup failed, says why and that the Agent was not changed", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "STOPPED",
        running_model: "",
        last_managed_update: {
          outcome: "BACKUP_FAILED",
          restore_point_id: null,
          failure_reason: "The Agent is still shutting down. Try again in a moment.",
        },
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const note = agentDetailPage.updateOutcome();
    await expect(note).toContainText(/backup could not be taken/i);
    await expect(note).toContainText(/still shutting down/i);
    await expect(note).toContainText(/not changed/i);
  });

  test("when the rollback failed, points at the restore points", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "ERROR",
        running_model: "",
        last_managed_update: { outcome: "ROLLBACK_FAILED", restore_point_id: null, failure_reason: null },
      },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const note = agentDetailPage.updateOutcome();
    await expect(note).toContainText(/rollback did not finish/i);
    await expect(note.getByRole("link", { name: /restore points/i })).toHaveAttribute(
      "href",
      new RegExp(`/agents/${MOCK_AGENT_ID}/configuration\\?section=restore$`),
    );
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
