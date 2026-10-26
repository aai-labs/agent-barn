import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_FOLDER_URL, mockFileSyncEntry, mockFileSyncStatus } from "../fixtures/file-sync";
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
    entries = [],
    activityReadStatus = 200,
  }: {
    status?: Record<string, unknown>;
    allowedActions?: string[];
    userContext?: unknown;
    readStatus?: number;
    entries?: Record<string, unknown>[];
    activityReadStatus?: number;
  } = {},
) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext });
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, allowed_actions: allowedActions } });
  await data.agents.interceptGetAgentHealthRequest();
  const fileSync = await data.fileSync.interceptFileSync({ status, readStatus });
  const activity = await data.fileSync.interceptFileSyncActivity({ entries, readStatus: activityReadStatus });
  const fileSyncPage = new AgentFileSyncPage(page);
  await fileSyncPage.goto(MOCK_AGENT_ID);
  return { fileSync, activity, fileSyncPage };
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

test.describe("Agent File sync activity", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("describes each kind of activity in plain words", async ({ page }) => {
    const at = "2026-10-26T09:00:00Z";
    const entries = [
      mockFileSyncEntry("edit_undone", "workspace/AGENTS.md", at),
      mockFileSyncEntry("restored", "workspace/report.md", at),
      mockFileSyncEntry("renamed_back", "workspace/notes.md", at),
      mockFileSyncEntry("moved_not_synced", "workspace/budget.xlsx", at),
      mockFileSyncEntry("folder_restored", null, at),
      mockFileSyncEntry("conflict_agent_won", "workspace/plan.md", at),
      mockFileSyncEntry("deleted_by_agent", "workspace/old.md", at),
      mockFileSyncEntry("skipped_too_large", "workspace/video.mp4", at),
      mockFileSyncEntry("skipped_name", "workspace/a:b.md", at),
      mockFileSyncEntry("skipped_no_space", "workspace/data.csv", at),
    ];
    const { fileSyncPage } = await open(page, { entries });

    const sentences = [
      "Someone edited workspace/AGENTS.md in OneDrive. Agent Barn manages that file, so the agent's copy was put back.",
      "workspace/report.md was deleted or moved away in OneDrive. The agent's copy was put back.",
      "workspace/notes.md was renamed or moved in OneDrive. It was moved back.",
      "workspace/budget.xlsx was added in OneDrive. The agent doesn't use it, so it was moved to _Not synced.",
      "The agent's folder was renamed, moved or deleted in OneDrive. It was put back.",
      "workspace/plan.md changed in the agent and in OneDrive at the same time. The agent's version was kept; the other edit is in OneDrive's version history.",
      "The agent deleted workspace/old.md, so it was deleted in OneDrive too.",
      "workspace/video.mp4 is over 100 MB, so it isn't synced.",
      "workspace/a:b.md has a name or path OneDrive doesn't accept, so it isn't synced.",
      "The agent's disk was full, so an edit to workspace/data.csv couldn't be applied yet. It will be retried.",
    ];
    await expect(fileSyncPage.activityEntries()).toHaveCount(sentences.length);
    for (const [index, sentence] of sentences.entries()) {
      await expect(fileSyncPage.activityEntries().nth(index)).toContainText(sentence);
    }
  });

  test("lists entries in the order the server gives them, newest first", async ({ page }) => {
    const { fileSyncPage } = await open(page, {
      entries: [
        mockFileSyncEntry("restored", "workspace/newer.md", "2026-10-26T10:00:00Z"),
        mockFileSyncEntry("restored", "workspace/older.md", "2026-10-25T10:00:00Z"),
      ],
    });

    await expect(fileSyncPage.activityEntries().first()).toContainText("workspace/newer.md");
    await expect(fileSyncPage.activityEntries().last()).toContainText("workspace/older.md");
  });

  test("loads the next page on request", async ({ page }) => {
    const entries = Array.from({ length: 21 }, (_, index) =>
      mockFileSyncEntry("restored", `workspace/${String(index).padStart(2, "0")}.md`, `2026-10-26T09:${String(59 - index).padStart(2, "0")}:00Z`),
    );
    const { activity, fileSyncPage } = await open(page, { entries });
    await expect(fileSyncPage.activityEntries()).toHaveCount(20);

    await fileSyncPage.loadMoreButton().click();

    await expect(fileSyncPage.activityEntries()).toHaveCount(21);
    await expect(fileSyncPage.activityEntries().last()).toContainText("workspace/20.md");
    await expect(fileSyncPage.loadMoreButton()).toHaveCount(0);
    expect(activity.requestedPages).toEqual([1, 2]);
  });

  test("says so when nothing has happened yet", async ({ page }) => {
    const { fileSyncPage } = await open(page);

    await expect(fileSyncPage.activityList().getByRole("heading", { name: "Sync activity" })).toBeVisible();
    await expect(fileSyncPage.activityList()).toContainText("Nothing has happened yet.");
    await expect(fileSyncPage.loadMoreButton()).toHaveCount(0);
  });

  test("shows a failed history read in place and retries it", async ({ page }) => {
    const { activity, fileSyncPage } = await open(page, {
      activityReadStatus: 500,
      entries: [mockFileSyncEntry("restored", "workspace/report.md", "2026-10-26T09:00:00Z")],
    });
    await expect(fileSyncPage.activityList()).toContainText("We couldn't load the sync history");
    await expect(fileSyncPage.card()).toContainText("Synced");

    activity.failReadsWith(200);
    await fileSyncPage.activityRetryButton().click();

    await expect(fileSyncPage.activityEntries()).toHaveCount(1);
  });
});
