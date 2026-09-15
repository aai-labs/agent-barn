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
    await expect(page.getByRole("tooltip")).toContainText("2 of 2");
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

  test("replaces the destructive action once the restore is accepted", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();
    // The volume restore is accepted; only the configuration replay fails.
    await dataSupport.agents.interceptSelectAgentTemplateRequest({
      status: 400,
      detail: "Required template skills must use the pinned versions: Calendar",
    });

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);

    let restoreCalls = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/restore")) restoreCalls += 1;
    });
    await configurationPage.restoreConfirmButton().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("was not re-applied");
    await expect(dialog).toContainText("pinned versions");
    await expect(dialog).toContainText("either lands whole or not at all");
    await expect(dialog).toContainText("volume restore is unaffected");

    // The destructive submit is gone: clicking again must not restore twice.
    await expect(configurationPage.restoreConfirmButton()).toHaveCount(0);
    await dialog.getByRole("button", { name: /^Done$/ }).click();
    await expect(dialog).toBeHidden();
    expect(restoreCalls).toBe(1);
  });

  test("replays the whole recorded configuration in one request", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await baseIntercepts(dataSupport);
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();
    await dataSupport.agents.interceptSelectAgentTemplateRequest();

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);

    const selectRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().endsWith("/configuration/select"),
    );
    let patchCalls = 0;
    page.on("request", (request) => {
      if (request.method() === "PATCH") patchCalls += 1;
    });
    await configurationPage.restoreConfirmButton().click();

    // The template pin, the skill pins and the runtime settings ride in the one
    // request the server validates and commits as a unit.
    const body = (await selectRequest).postDataJSON();
    expect(body.selection_type).toBe("organization");
    expect(body.template_key).toBe(MOCK_TEMPLATE_KEY);
    expect(body.template_version).toBe(1);
    expect(body).toHaveProperty("skill_versions");
    expect(body).toHaveProperty("verbose_mode");
    expect(body.model).toBe("litellm/gpt-5-mini");
    expect(patchCalls).toBe(0);
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
    await expect(page.getByRole("tooltip")).toContainText("1 of 1");
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

  test("rebuilds a configuration retry from a fresh read of the Agent", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    // The Agent moves on after this page rendered, as another tab would move it.
    let agentBody: unknown = { ...stoppedAgent, updated_at: "2026-05-14T09:14:00Z" };
    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(agentBody),
      });
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();
    await dataSupport.agents.interceptSelectAgentTemplateRequest({
      status: 409,
      detail: "The Agent changed since this page was loaded",
    });

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);
    await configurationPage.restoreConfirmButton().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("was not re-applied");

    // Whatever changed the Agent has now settled; the retry must pick that up
    // rather than resubmitting the timestamp this page opened with.
    agentBody = { ...stoppedAgent, updated_at: "2026-05-14T11:45:00Z" };
    await dataSupport.agents.interceptSelectAgentTemplateRequest();

    const retryRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().endsWith("/configuration/select"),
    );
    await dialog.getByRole("button", { name: /retry configuration/i }).click();

    const body = (await retryRequest).postDataJSON();
    expect(body.expected_agent_updated_at).toBe("2026-05-14T11:45:00Z");
  });

  test("cannot be dismissed while the replay is still working", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    // The Agent read that the replay builds its request from is held open. No
    // mutation is pending during that window, so nothing but an explicit
    // whole-operation pending state keeps the dialog from being closed.
    let holdAgentRead = false;
    let releaseAgentRead: () => void = () => {};
    const agentRead = new Promise<void>((resolve) => {
      releaseAgentRead = resolve;
    });

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      if (holdAgentRead) await agentRead;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(stoppedAgent),
      });
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetRestorePointsRequest();
    await dataSupport.agents.interceptRestoreRestorePointRequest();
    await dataSupport.agents.interceptSelectAgentTemplateRequest({
      status: 400,
      detail: "Model litellm/gpt-5-mini is not in the allowed model list",
    });

    await openRestorePoints(configurationPage);
    await configurationPage.restoreButton().click();
    await configurationPage.reapplyConfigurationCheckbox().check();
    await configurationPage.restoreConfirmNameInput().fill(mockAgent.name);

    holdAgentRead = true;
    await configurationPage.restoreConfirmButton().click();

    const dialog = page.getByRole("dialog");
    // The restore has been accepted and the replay is mid-flight: every way out
    // stays shut until there is an outcome to show.
    await expect(dialog.getByRole("button", { name: /restoring/i })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: /^Cancel$/ })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();

    releaseAgentRead();

    // Only once the outcome exists does the dialog become dismissable, and the
    // outcome is on screen rather than written into an unmounted component.
    await expect(dialog).toContainText("was not re-applied");
    await expect(dialog).toContainText("not in the allowed model list");
    await expect(dialog.getByRole("button", { name: /^Done$/ })).toBeEnabled();
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
