import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
  mockPreResetPoint,
  mockReadyPreResetPoint,
  mockRestorePoint,
  mockRestorePointsPage,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const stoppedAgent = { ...mockAgent, status: "STOPPED" };

async function openDangerZone(page: AgentConfigurationPage) {
  await page.goto(MOCK_AGENT_ID, TEST_ORG_ID);
  await page.sectionButton("Danger zone").click();
}

async function baseIntercepts(dataSupport: DataSupport, agent: unknown = stoppedAgent) {
  await dataSupport.auth.interceptRefreshRequest();
  await dataSupport.users.interceptGetUserContextRequest();
  await dataSupport.users.interceptGetOrganizationsRequest();
  await dataSupport.agents.interceptGetAgentRequest({ body: agent });
  await dataSupport.agents.interceptGetAgentConfigurationRequest();
}

test.describe("Agent reset", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("resets a stopped Agent after confirmation and says to start it", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    // The API resolves the Job when the backup row is read, so the fixture moves the
    // row along between reads.
    let listBody: unknown = mockRestorePointsPage({ items: [mockRestorePoint] });

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({ body: () => listBody });
    await dataSupport.agents.interceptResetAgentRequest();

    await openDangerZone(configurationPage);
    await expect(configurationPage.resetButton()).toBeEnabled();
    await expect(configurationPage.resetOutcome()).toBeHidden();

    await configurationPage.resetButton().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Before reset");
    await expect(dialog).toContainText("long-term memory are kept");

    const resetRequest = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/reset`) && request.method() === "POST",
    );
    listBody = mockRestorePointsPage({ items: [mockPreResetPoint, mockRestorePoint] });
    await configurationPage.resetConfirmButton().click();
    await resetRequest;
    await expect(dialog).toBeHidden();

    await expect(configurationPage.resetButton()).toBeDisabled();
    await expect(configurationPage.resetButton()).toContainText("Resetting");

    // Nothing is clicked from here: the list polls itself to a terminal status.
    listBody = mockRestorePointsPage({ items: [mockReadyPreResetPoint, mockRestorePoint] });
    await expect(configurationPage.resetOutcome()).toContainText("Start the Agent to boot it fresh");
    await expect(configurationPage.resetButton()).toBeEnabled();
  });

  test("is offered only once the Agent is stopped, and says why until then", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport, { ...mockAgent, status: "RUNNING" });
    await dataSupport.agents.interceptGetRestorePointsRequest();

    await openDangerZone(configurationPage);
    await expect(configurationPage.resetButton()).toBeDisabled();
    await expect(configurationPage.resetReason()).toHaveText("Stop the Agent before resetting it.");
  });

  test("is refused for someone who cannot manage the Agent's lifecycle", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport, {
      ...stoppedAgent,
      allowed_actions: mockAgentAllowedActions.filter((action) => action !== "agent.lifecycle.manage"),
    });
    await dataSupport.agents.interceptGetRestorePointsRequest();

    await openDangerZone(configurationPage);
    await expect(configurationPage.resetButton()).toBeDisabled();
    await expect(configurationPage.resetReason()).toContainText("permission");
  });

  test("waits while another restore point operation is running", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({ items: [{ ...mockRestorePoint, status: "CAPTURING" }] }),
    });

    await openDangerZone(configurationPage);
    await expect(configurationPage.resetButton()).toBeDisabled();
    await expect(configurationPage.resetReason()).toContainText("already running");
  });

  test("says so when the reset took its backup but did not finish", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockReadyPreResetPoint,
            failure_reason:
              "The backup was saved, but the reset did not finish, so some of the Agent's files may be gone.",
          },
          mockRestorePoint,
        ],
      }),
    });

    await openDangerZone(configurationPage);
    await expect(configurationPage.resetOutcome()).toContainText("did not finish");
    await expect(configurationPage.resetOutcome().getByRole("link", { name: "View the backup" })).toBeVisible();
    // Another reset is the way to finish it, so the button is still offered.
    await expect(configurationPage.resetButton()).toBeEnabled();
  });

  test("tells you when a reset fails, and keeps saying so once the Agent is running", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    let listBody: unknown = mockRestorePointsPage({ items: [mockRestorePoint] });
    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({ body: () => listBody });
    await dataSupport.agents.interceptResetAgentRequest();

    await openDangerZone(configurationPage);
    await configurationPage.resetButton().click();
    listBody = mockRestorePointsPage({ items: [mockPreResetPoint, mockRestorePoint] });
    await configurationPage.resetConfirmButton().click();

    const failed = { ...mockPreResetPoint, status: "FAILED", failure_reason: "Unknown RESTORE_POINT_MODE: reset" };
    listBody = mockRestorePointsPage({ items: [failed, mockRestorePoint] });
    await expect(page.locator("[data-sonner-toast]")).toContainText("Unknown RESTORE_POINT_MODE: reset");

    // Starting the Agent used to be what hid the failure from the person who asked for it.
    await baseIntercepts(dataSupport, mockAgent);
    await openDangerZone(configurationPage);
    await expect(configurationPage.resetOutcome()).toContainText("did not complete");
  });

  test("shows a refusal from the server as an error and leaves the dialog usable", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptResetAgentRequest({
      status: 409,
      detail: "The Agent is still shutting down. Try again in a moment.",
    });

    await openDangerZone(configurationPage);
    await configurationPage.resetButton().click();
    await configurationPage.resetConfirmButton().click();

    await expect(page.getByText("The Agent is still shutting down. Try again in a moment.")).toBeVisible();
    await expect(configurationPage.resetButton()).toBeEnabled();
  });
});
