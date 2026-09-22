import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import {
  MOCK_AGENT_ID,
  MOCK_TEMPLATE_KEY,
  mockAgent,
  mockCapturingRestorePoint,
  mockPreRestorePoint,
  mockRestorePoint,
  mockRestorePointsPage,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const stoppedAgent = { ...mockAgent, status: "STOPPED" };

async function openRestorePoints(page: AgentConfigurationPage) {
  await page.goto(MOCK_AGENT_ID, TEST_ORG_ID);
  await page.sectionButton("Restore points").click();
}

async function baseIntercepts(dataSupport: DataSupport, agent: unknown = stoppedAgent) {
  await dataSupport.auth.interceptRefreshRequest();
  await dataSupport.users.interceptGetUserContextRequest();
  await dataSupport.users.interceptGetOrganizationsRequest();
  await dataSupport.agents.interceptGetAgentRequest({ body: agent });
  await dataSupport.agents.interceptGetAgentConfigurationRequest();
}

test.describe("Agent restore points", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("captures a restore point and follows it through to ready", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    // The API resolves a capture only when the row is read, so the fixture moves
    // the row along between reads rather than on a fixed number of them.
    let listBody: unknown = mockRestorePointsPage({ items: [], manualCount: 0 });

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({ body: () => listBody });
    await dataSupport.agents.interceptCreateRestorePointRequest();

    await openRestorePoints(configurationPage);
    await expect(page.getByText("No restore points yet.")).toBeVisible();

    listBody = mockRestorePointsPage({ items: [mockCapturingRestorePoint], manualCount: 1 });
    await configurationPage.captureRestorePointButton().click();

    const row = configurationPage.restorePointRow("Before the rewrite");
    await expect(row).toContainText("Capturing");

    // Nothing is clicked from here: the list polls itself to a terminal status.
    listBody = mockRestorePointsPage({ items: [mockRestorePoint], manualCount: 1 });
    await expect(row).toContainText("Ready");
    await expect(row).toContainText("2.0 MB");
    await expect(row).toContainText("42 files");
  });

  test("restores only after the Agent's name is typed", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("runtime");
    await expect(dialog).toContainText("session history rolls back");
    await expect(configurationPage.reapplyConfigurationCheckbox()).not.toBeChecked();
    await expect(configurationPage.restoreConfirmButton()).toBeDisabled();

    await configurationPage.restoreConfirmNameInput().fill("Not the agent");
    await expect(configurationPage.restoreConfirmButton()).toBeDisabled();

    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);
    await expect(configurationPage.restoreConfirmButton()).toBeEnabled();

    const restoreRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/restore-points/") &&
        request.url().endsWith("/restore") &&
        request.method() === "POST",
    );
    await configurationPage.restoreConfirmButton().click();
    await restoreRequest;
    await expect(dialog).toBeHidden();
  });

  test("refuses to capture at the cap and names the count", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [mockRestorePoint, mockPreRestorePoint],
        cap: 2,
        manualCount: 2,
      }),
    });

    await openRestorePoints(configurationPage);
    await expect(configurationPage.captureRestorePointButton()).toBeDisabled();

    await configurationPage.captureAction().hover();
    await expect(page.getByRole("tooltip")).toContainText("All 2 captures are used");
  });

  test("will not capture while the Agent is running", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport, { ...mockAgent, status: "RUNNING" });
    await dataSupport.agents.interceptGetRestorePointsRequest();

    await openRestorePoints(configurationPage);
    await expect(configurationPage.captureRestorePointButton()).toBeDisabled();

    await configurationPage.captureAction().hover();
    await expect(page.getByRole("tooltip")).toContainText("Stop the Agent");
  });

  test("shows a failed capture's reason and offers to delete it", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockRestorePoint,
            status: "FAILED",
            archive_bytes: null,
            file_count: null,
            failure_reason: "The destination volume ran out of space.",
          },
        ],
        manualCount: 0,
      }),
    });
    await dataSupport.agents.interceptDeleteRestorePointRequest();

    await openRestorePoints(configurationPage);
    const row = configurationPage.restorePointRow("Before the rewrite");
    await expect(row).toContainText("Failed");
    await expect(row).toContainText("ran out of space");

    const deleteRequest = page.waitForRequest(
      (request) => request.method() === "DELETE" && request.url().includes("/restore-points/"),
    );
    await row.getByRole("button", { name: /^Delete Before the rewrite$/ }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /delete restore point/i })
      .click();
    await deleteRequest;
  });

  test("shows the captured configuration beside the Agent's current one", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockRestorePoint,
            config_manifest: {
              ...mockRestorePoint.config_manifest,
              model: "litellm/gpt-4o-mini",
              verbose_mode: true,
            },
          },
        ],
      }),
    });

    await openRestorePoints(configurationPage);
    const row = configurationPage.restorePointRow("Before the rewrite");
    await row.getByRole("button", { name: "Configuration" }).click();

    await expect(row).toContainText("litellm/gpt-4o-mini");
    await expect(row).toContainText("litellm/gpt-5-mini");
    await expect(row).toContainText("Differs from the Agent's configuration now");
  });

  test("does not offer configuration replay without agent.update", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport, {
      ...stoppedAgent,
      // Lifecycle without configuration rights: the volume operation is allowed,
      // the replay is not.
      allowed_actions: ["agent.read", "activity.read", "agent.lifecycle.manage"],
    });
    await dataSupport.agents.interceptGetRestorePointsRequest();

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();

    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(configurationPage.reapplyConfigurationCheckbox()).toHaveCount(0);
  });

  test("reports a scope change the rendered label cannot show", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockRestorePoint,
            config_manifest: {
              ...mockRestorePoint.config_manifest,
              // Same key and version as the Agent's current pin, different scope:
              // an Organization fork shadows its platform lineage at the same key
              // and restarts at v1, so these two render identically.
              template_selection_type: "platform",
              template_key: MOCK_TEMPLATE_KEY,
              template_version: 1,
            },
          },
        ],
      }),
    });

    await openRestorePoints(configurationPage);
    const row = configurationPage.restorePointRow("Before the rewrite");
    await row.getByRole("button", { name: "Configuration" }).click();

    await expect(row).toContainText("Built-in platform");
    await expect(row).toContainText("Organization");
    await expect(row).toContainText("Differs from the Agent's configuration now");
  });

  test("loads restore points beyond the first page", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    const firstPage = Array.from({ length: 20 }, (_, index) => ({
      ...mockPreRestorePoint,
      id: `77777777-7777-4777-8777-${String(index).padStart(12, "0")}`,
      label: `Automatic backup ${index}`,
    }));

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: () => ({
        ...mockRestorePointsPage({ items: firstPage, manualCount: 1 }),
        total: 21,
      }),
      secondPageBody: {
        ...mockRestorePointsPage({ items: [mockRestorePoint], manualCount: 1 }),
        page: 2,
        total: 21,
      },
    });

    await openRestorePoints(configurationPage);
    await expect(configurationPage.restorePointRows()).toHaveCount(20);
    await expect(configurationPage.restorePointRow("Before the rewrite")).toHaveCount(0);

    await page.getByRole("button", { name: /load more/i }).click();
    await expect(configurationPage.restorePointRow("Before the rewrite")).toBeVisible();
  });

  test("shows when the archive was written, not when it was asked for", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockRestorePoint,
            created_at: "2026-05-14T09:00:00Z",
            captured_at: "2026-05-16T17:30:00Z",
          },
          {
            ...mockCapturingRestorePoint,
            id: "88888888-8888-4888-8888-888888888888",
            label: "Still running",
            created_at: "2026-05-14T09:00:00Z",
          },
        ],
      }),
    });

    await openRestorePoints(configurationPage);

    const ready = configurationPage.restorePointRow("Before the rewrite");
    await expect(ready).toContainText("May 16, 2026");
    await expect(ready).not.toContainText("requested");

    // No archive yet, so the row falls back to the request time and says so.
    const running = configurationPage.restorePointRow("Still running");
    await expect(running).toContainText("May 14, 2026");
    await expect(running).toContainText("(requested)");
  });

  test("keeps capture disabled until capacity is known", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    // The cap-reached answer arrives late. Before it does, the hook has no cap and
    // no entries — which must not read as "room to spare".
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/v1/organizations/*/agents/*/restore-points*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await held;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          mockRestorePointsPage({ items: [mockRestorePoint], cap: 1, manualCount: 1 }),
        ),
      });
    });

    await openRestorePoints(configurationPage);
    await expect(configurationPage.captureRestorePointButton()).toBeDisabled();
    await configurationPage.captureAction().hover();
    await expect(page.getByRole("tooltip")).toContainText("Checking");

    release();
    await expect(configurationPage.restorePointRow("Before the rewrite")).toBeVisible();
    await expect(configurationPage.captureRestorePointButton()).toBeDisabled();
    await configurationPage.captureAction().hover();
    await expect(page.getByRole("tooltip")).toContainText("All 1 captures are used");
  });

  test("keeps capture disabled when the list cannot be loaded at all", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({ status: 500 });

    await openRestorePoints(configurationPage);
    await expect(configurationPage.captureRestorePointButton()).toBeDisabled();
    await configurationPage.captureAction().hover();
    await expect(page.getByRole("tooltip")).toContainText("capacity is unknown");
  });

  test("says what an automatic entry was taken for", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({ items: [mockPreRestorePoint, mockRestorePoint] }),
    });

    await openRestorePoints(configurationPage);

    const automatic = configurationPage.restorePointRow("Automatic backup before restore");
    await expect(automatic).toContainText("Before restore");
    await expect(automatic).not.toContainText("System-created");
    // A manual capture carries no badge at all.
    await expect(
      configurationPage.restorePointRow("Before the rewrite"),
    ).not.toContainText("Before restore");
  });

  test("a refused replay stops the restore before anything is overwritten", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const skillId = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          {
            ...mockRestorePoint,
            config_manifest: {
              ...mockRestorePoint.config_manifest,
              skills: [{ skill_id: skillId, name: "Calendar", pinned_version: 3 }],
            },
          },
        ],
      }),
    });
    await dataSupport.agents.interceptRestoreRestorePointRequest({
      status: 400,
      detail: `Version 3 not found for skill ${skillId}`,
    });

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);
    await configurationPage.restoreConfirmButton().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("The restore was not started");
    // Named from the manifest rather than shown as a UUID.
    await expect(dialog).toContainText("Calendar");
    await expect(dialog).not.toContainText(skillId);
    await expect(dialog).toContainText("Nothing on the Agent's volume has been changed");
  });

  test("sends the replay choice with the restore and then closes", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);

    const request = page.waitForRequest(
      (r) => r.method() === "POST" && r.url().endsWith("/restore"),
    );
    let patchOrSelect = 0;
    page.on("request", (r) => {
      if (r.url().endsWith("/configuration/select") || r.method() === "PATCH") patchOrSelect += 1;
    });
    await configurationPage.restoreConfirmButton().click();

    expect((await request).postDataJSON().reapply_configuration).toBe(true);
    await expect(page.getByRole("dialog")).toBeHidden();
    // The configuration is the server's job now; the browser writes nothing.
    expect(patchOrSelect).toBe(0);
  });

  test("says a replay is still owed, and reports one that did not land", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [
          { ...mockRestorePoint, status: "RESTORING", reapply_configuration: true },
          {
            ...mockPreRestorePoint,
            configuration_error: "Organization Template Version not found",
          },
        ],
      }),
    });

    await openRestorePoints(configurationPage);

    await expect(configurationPage.restorePointRow("Before the rewrite")).toContainText(
      "will be re-applied once the files are back",
    );
    const failed = configurationPage.restorePointRow("Automatic backup before restore");
    await expect(failed).toContainText("The recorded configuration was not re-applied");
    await expect(failed.getByRole("button", { name: /re-apply configuration/i })).toBeVisible();
  });

  test("refreshes the Agent's configuration once a replay lands", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    // Owed first, then settled — the transition the browser never asked for.
    let owed = true;
    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: () =>
        mockRestorePointsPage({
          items: [{ ...mockRestorePoint, reapply_configuration: owed }],
        }),
    });

    let agentReads = 0;
    page.on("request", (request) => {
      if (
        request.method() === "GET" &&
        request.url().includes(`/agents/${MOCK_AGENT_ID}`) &&
        !request.url().includes("restore-points")
      ) {
        agentReads += 1;
      }
    });

    await openRestorePoints(configurationPage);
    await expect(configurationPage.restorePointRow("Before the rewrite")).toContainText(
      "will be re-applied once the files are back",
    );
    const readsWhileOwed = agentReads;

    owed = false;
    // Polling outlasts the status precisely so the replay is picked up and seen.
    await expect(configurationPage.restorePointRow("Before the rewrite")).not.toContainText(
      "will be re-applied once the files are back",
    );
    await expect.poll(() => agentReads).toBeGreaterThan(readsWhileOwed);
  });

  test("shows how many captures are used, and that backups are not counted", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    // Two entries, but only one of them is a capture the user took.
    await dataSupport.agents.interceptGetRestorePointsRequest({
      body: mockRestorePointsPage({
        items: [mockRestorePoint, mockPreRestorePoint],
        cap: 5,
        manualCount: 1,
      }),
    });

    await openRestorePoints(configurationPage);

    const capacity = page.getByTestId("restore-point-capacity");
    await expect(capacity).toContainText("1 of 5 captures used");
    await expect(capacity).toContainText("Automatic backups taken before a restore don't count");
    await expect(configurationPage.restorePointRows()).toHaveCount(2);
  });

  test("lets a viewer read the list without offering any action", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport, {
      ...stoppedAgent,
      allowed_actions: ["agent.read", "activity.read", "cost.read"],
    });
    await dataSupport.agents.interceptGetRestorePointsRequest();

    await openRestorePoints(configurationPage);
    await expect(configurationPage.restorePointRow("Before the rewrite")).toBeVisible();
    await expect(configurationPage.captureRestorePointButton()).toHaveCount(0);
    await expect(configurationPage.restoreButton()).toHaveCount(0);
  });
});
