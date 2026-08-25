import { expect, test, type Page } from "@playwright/test";

import { mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

async function chooseTemplate(page: Page) {
  await page.getByRole("combobox").nth(1).click();
  await page.getByRole("option", { name: "General Purpose · v1" }).click();
}

test.describe("Hire Dialog", () => {
  let dashboardPage: DashboardPage;
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentsRequest();
    await dataSupport.agents.interceptGetAgentHealthRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetModelsRequest();

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("hires a headless Agent without communication credentials", async ({ page }) => {
    await dataSupport.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, name: "Aria", status: "STOPPED", agent_type: "hermes" },
    });
    await dataSupport.agents.interceptStartAgentRequest();

    await expect(page.getByRole("heading", { name: "Hire a headless Agent" })).toBeVisible();
    await expect(
      page.getByText("Communication connections and integration credentials are configured independently after hiring."),
    ).toBeVisible();
    await expect(page.getByPlaceholder(/xapp-/i)).toHaveCount(0);
    await expect(page.getByPlaceholder(/discord bot token/i)).toHaveCount(0);

    await chooseTemplate(page);
    const createRequest = page.waitForRequest(
      (request) => request.url().endsWith("/agents") && request.method() === "POST",
    );
    const startRequest = page.waitForRequest(
      (request) => request.url().endsWith(`/${mockAgent.id}/start`) && request.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();

    const payload = (await createRequest).postDataJSON();
    expect(payload).toEqual({
      name: "Aria",
      agent_type: "hermes",
      template_key: "general-purpose",
      template_version: 1,
      model: "litellm/openrouter/z-ai/glm-5.2",
      approval_mode: "auto",
    });
    await startRequest;
    await expect(page.getByText("Aria was hired successfully.")).toBeVisible();
  });

  test("allows choosing a runtime independently of communication platforms", async ({ page }) => {
    await dataSupport.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, name: "Aria", status: "STOPPED", agent_type: "openclaw" },
    });
    await dataSupport.agents.interceptStartAgentRequest();

    // Pick a non-default approval mode while still on Hermes, then switch to
    // OpenClaw, to prove the stale value is dropped rather than sent along.
    await page.getByRole("combobox").nth(2).click();
    await page.getByRole("option", { name: "Manual" }).click();

    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "OpenClaw" }).click();
    await chooseTemplate(page);

    const createRequest = page.waitForRequest(
      (request) => request.url().endsWith("/agents") && request.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();

    const payload = (await createRequest).postDataJSON();
    expect(payload).toMatchObject({
      agent_type: "openclaw",
      template_key: "general-purpose",
    });
    expect(payload).not.toHaveProperty("approval_mode");
  });

  test("shows Command approval only for the Hermes runtime", async ({ page }) => {
    await expect(page.getByText("Command approval", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox")).toHaveCount(3);

    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "OpenClaw" }).click();

    await expect(page.getByText("Command approval", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("combobox")).toHaveCount(2);
  });

  test("keeps hire disabled until a template is selected", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Hire Agent", exact: true })).toBeDisabled();
    await chooseTemplate(page);
    await expect(page.getByRole("button", { name: "Hire Agent", exact: true })).toBeEnabled();
  });

  test("shows create failures and does not start an Agent", async ({ page }) => {
    await dataSupport.agents.interceptCreateAgentRequest({
      status: 409,
      detail: "An Agent named Aria already exists",
    });
    let startRequests = 0;
    await page.route("**/api/v1/organizations/*/agents/*/start", async (route) => {
      startRequests += 1;
      await route.abort();
    });

    await chooseTemplate(page);
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();

    await expect(page.getByText("An Agent named Aria already exists")).toBeVisible();
    expect(startRequests).toBe(0);
  });
});
