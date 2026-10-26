import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_FOLDER_URL, mockFileSyncStatus } from "../fixtures/file-sync";
import UserContext from "../fixtures/user-context.json";
import { AgentFileSyncPage } from "../pages/agent-file-sync-page.po";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

function memberContext() {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({ ...membership, role: "MEMBER" })),
  };
}

async function open(
  page: Page,
  {
    status = mockFileSyncStatus(),
    allowedActions = mockAgentAllowedActions,
    userContext,
    readStatus = 200,
  }: {
    status?: Record<string, unknown>;
    allowedActions?: string[];
    userContext?: unknown;
    readStatus?: number;
  } = {},
) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext });
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, allowed_actions: allowedActions } });
  await data.agents.interceptGetAgentHealthRequest();
  const fileSync = await data.fileSync.interceptFileSync({ status, readStatus });
  const fileSyncPage = new AgentFileSyncPage(page);
  await fileSyncPage.goto(MOCK_AGENT_ID);
  return { fileSync, fileSyncPage };
}

test.describe("Agent File sync", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const states: [Record<string, unknown>, string][] = [
    [mockFileSyncStatus(), "Synced"],
    [mockFileSyncStatus({ state: "waiting_for_restart", last_contact_at: null }), "Starts syncing after the next restart"],
    [mockFileSyncStatus({ enabled: false, state: "turned_off" }), "Turned off"],
    [mockFileSyncStatus({ state: "setting_up", folder_url: null }), "Setting up the folder in OneDrive"],
    [
      mockFileSyncStatus({ state: "throttled", retry_at: "2026-10-26T10:05:00Z" }),
      "OneDrive asked Agent Barn to slow down",
    ],
    [mockFileSyncStatus({ state: "not_syncing" }), "This agent hasn't checked in with sync since"],
    [mockFileSyncStatus({ state: "not_connected", provider: null, folder_url: null, last_contact_at: null }), "Not connected"],
  ];
  for (const [status, text] of states) {
    test(`says "${text}" for ${status.state}`, async ({ page }) => {
      const { fileSyncPage } = await open(page, { status });

      await expect(fileSyncPage.card()).toContainText(text);
    });
  }

  test("opens the Agent's folder at the provider in a new tab", async ({ page }) => {
    const { fileSyncPage } = await open(page);

    await expect(fileSyncPage.openFolderLink()).toHaveText(/Open in OneDrive/);
    await expect(fileSyncPage.openFolderLink()).toHaveAttribute("href", MOCK_FOLDER_URL);
    await expect(fileSyncPage.openFolderLink()).toHaveAttribute("target", "_blank");
  });

  test("offers no folder link while the folder doesn't exist", async ({ page }) => {
    const { fileSyncPage } = await open(page, { status: mockFileSyncStatus({ state: "setting_up", folder_url: null }) });

    await expect(fileSyncPage.card()).toContainText("Setting up");
    await expect(fileSyncPage.openFolderLink()).toHaveCount(0);
  });

  test("points an Owner to Organization settings when not connected", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      status: mockFileSyncStatus({ state: "not_connected", provider: null, folder_url: null }),
    });

    await expect(fileSyncPage.organizationSettingsLink()).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=sync`,
    );
  });

  test("tells a Member who can connect, without a link", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      status: mockFileSyncStatus({ state: "not_connected", provider: null, folder_url: null }),
      userContext: memberContext(),
    });

    await expect(fileSyncPage.card()).toContainText("An Owner or Admin can connect one in Organization settings.");
    await expect(fileSyncPage.organizationSettingsLink()).toHaveCount(0);
  });

  test("shows the switch's position in every state, even while not connected", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      status: mockFileSyncStatus({ enabled: false, state: "not_connected", provider: null, folder_url: null }),
    });

    await expect(fileSyncPage.syncSwitch()).not.toBeChecked();
  });

  test("turns sync off and shows the new status", async ({ page }) => {
    const { fileSync, fileSyncPage } = await open(page);
    await expect(fileSyncPage.syncSwitch()).toBeChecked();

    const put = page.waitForRequest((request) => request.url().endsWith("/file-sync") && request.method() === "PUT");
    await fileSyncPage.syncSwitch().click();
    await put;

    await expect(fileSyncPage.card()).toContainText("Turned off");
    await expect(fileSyncPage.syncSwitch()).not.toBeChecked();
    expect(fileSync.requests.filter((request) => request.method === "PUT")).toEqual([
      { method: "PUT", body: { enabled: false } },
    ]);
  });

  test("hides the switch from someone who can't change the Agent", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      allowedActions: mockAgentAllowedActions.filter((action) => action !== "agent.update"),
    });

    await expect(fileSyncPage.card()).toContainText("Synced");
    await expect(fileSyncPage.syncSwitch()).toHaveCount(0);
  });

  test("is not offered to someone who can't read the Agent's activity", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      allowedActions: mockAgentAllowedActions.filter((action) => action !== "activity.read"),
    });

    await expect(fileSyncPage.sectionLink("Overview")).toBeVisible();
    await expect(fileSyncPage.sectionLink("File sync")).toHaveCount(0);
    await expect(fileSyncPage.card()).toHaveCount(0);
  });

  test("shows a failed read inline and retries it", async ({ page }) => {
    const { fileSync, fileSyncPage } = await open(page, { readStatus: 500 });

    await expect(page.getByText("We couldn't load file sync")).toBeVisible();
    fileSync.failReadsWith(200);
    await fileSyncPage.retryButton().click();

    await expect(fileSyncPage.card()).toContainText("Synced");
  });
});
