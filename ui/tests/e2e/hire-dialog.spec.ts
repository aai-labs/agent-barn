import { expect, test, type Page } from "@playwright/test";

import {
  mockAgent,
  mockProvisioningError,
  mockTemplates,
} from "../pages/data-support/agent-data-support.po";
import { mockCustomSkill, mockJiraSkill } from "../pages/data-support/skill-data-support.po";
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
    await expect(page.getByRole("radio", { name: /use organization default/i })).toBeChecked();
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
      approval_mode: "auto",
    });
    await startRequest;
    await expect(page.getByText("Aria was hired successfully.")).toBeVisible();
  });

  test("configures template-required skill credentials before creating the Agent", async ({ page }) => {
    const jiraRequiredSkill = {
      id: mockJiraSkill.id,
      name: mockJiraSkill.name,
      source: mockJiraSkill.source,
      required_providers: mockJiraSkill.requiredProviders,
      tools_pointer: mockJiraSkill.toolsPointer,
      required: true,
      created_at: mockJiraSkill.createdAt,
      updated_at: mockJiraSkill.updatedAt,
      group_key: null,
    };
    await dataSupport.agents.interceptGetTemplatesRequest({
      body: {
        page: 1,
        page_size: 50,
        total: 1,
        items: [{ ...mockTemplates[0], required_skills: [jiraRequiredSkill] }],
      },
    });
    await dataSupport.skills.interceptGetSkillsRequest({ body: [mockJiraSkill] });
    await dataSupport.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, name: "Aria", status: "STOPPED", agent_type: "hermes" },
    });
    await dataSupport.agents.interceptStartAgentRequest();

    // The dialog's initial template query is already cached by the dashboard;
    // reload so this test-specific template response is consumed.
    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
    await chooseTemplate(page);
    await expect(page.getByText("Template skills and credentials")).toBeVisible();
    await expect(page.getByText("jira", { exact: true })).toBeVisible();

    await page.getByPlaceholder("https://your-domain.atlassian.net").fill("https://acme.atlassian.net");
    await page.getByText("Non-scoped token", { exact: true }).click();
    await page.getByPlaceholder("you@example.com").fill("user@example.com");
    await page.locator('input[type="password"]').fill("jira-token");

    const createRequest = page.waitForRequest(
      (request) => request.url().endsWith("/agents") && request.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();
    const payload = (await createRequest).postDataJSON();

    expect(payload.skill_ids).toEqual([mockJiraSkill.id]);
    expect(payload.secrets).toEqual([
      {
        provider: "jira",
        content: {
          site_url: "https://acme.atlassian.net",
          use_scoped_token: false,
          email: "user@example.com",
          api_token: "jira-token",
        },
      },
    ]);
  });

  test("keeps standalone template-required skills in the required section", async ({ page }) => {
    const jiraRequiredSkill = {
      id: mockJiraSkill.id,
      name: mockJiraSkill.name,
      source: mockJiraSkill.source,
      required_providers: mockJiraSkill.requiredProviders,
      tools_pointer: mockJiraSkill.toolsPointer,
      required: true,
      created_at: mockJiraSkill.createdAt,
      updated_at: mockJiraSkill.updatedAt,
      group_key: null,
    };
    await dataSupport.agents.interceptGetTemplatesRequest({
      body: {
        page: 1,
        page_size: 50,
        total: 1,
        items: [{ ...mockTemplates[0], required_skills: [jiraRequiredSkill] }],
      },
    });
    await dataSupport.skills.interceptGetSkillsRequest({
      body: [mockJiraSkill, mockCustomSkill],
    });

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
    await chooseTemplate(page);

    const requiredSection = page.getByRole("region", { name: "Required by template" });
    await expect(requiredSection).toBeVisible();
    await expect(requiredSection.getByText("Jira", { exact: true })).toBeVisible();
    await expect(requiredSection.getByText("my-tool", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Additional skills" })).toBeVisible();
    await expect(page.getByText("my-tool", { exact: true })).toBeVisible();
  });

  test("shows credential validation failures as alerts inside the credential form", async ({ page }) => {
    const jiraRequiredSkill = {
      id: mockJiraSkill.id,
      name: mockJiraSkill.name,
      source: mockJiraSkill.source,
      required_providers: mockJiraSkill.requiredProviders,
      tools_pointer: mockJiraSkill.toolsPointer,
      required: true,
      created_at: mockJiraSkill.createdAt,
      updated_at: mockJiraSkill.updatedAt,
      group_key: null,
    };
    await dataSupport.agents.interceptGetTemplatesRequest({
      body: {
        page: 1,
        page_size: 50,
        total: 1,
        items: [{ ...mockTemplates[0], required_skills: [jiraRequiredSkill] }],
      },
    });
    await dataSupport.skills.interceptGetSkillsRequest({ body: [mockJiraSkill] });
    await dataSupport.agents.interceptCreateAgentRequest({
      status: 400,
      detail: "Invalid email or API token",
    });

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
    await chooseTemplate(page);
    await expect(page.getByText("Template skills and credentials")).toBeVisible();

    await page.getByPlaceholder("https://your-domain.atlassian.net").fill("https://acme.atlassian.net");
    await page.getByText("Non-scoped token", { exact: true }).click();
    await page.getByPlaceholder("you@example.com").fill("user@example.com");
    await page.locator('input[type="password"]').fill("jira-token");
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();

    const credentialsSection = page.locator("section").filter({ hasText: "Template skills and credentials" });
    await expect(credentialsSection.getByRole("alert")).toContainText("Invalid email or API token");
    await expect(page.locator("footer").getByRole("alert")).toHaveCount(0);
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

  test("a start refused by the cluster explains itself and says the Agent exists", async ({
    page,
  }) => {
    await dataSupport.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, name: "Aria", status: "STOPPED" },
    });
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await chooseTemplate(page);
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();

    const alert = page.getByTestId("hire-provisioning-error");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Namespace quota exhausted");
    await expect(alert).toContainText("run out of resource quota");
    await expect(alert).toContainText("requests.storage: requested 1Gi");
    // Creation succeeded before the start failed, so the Agent is on the team page.
    await expect(alert).toContainText("was created and is waiting on your team page");
    await expect(page.getByText("Request failed with status code")).toHaveCount(0);
  });

  test("retrying a failed hire starts the created Agent instead of creating a second", async ({
    page,
  }) => {
    let createRequests = 0;
    await page.route("**/api/v1/organizations/*/agents", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      createRequests += 1;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ ...mockAgent, name: "Aria", status: "STOPPED" }),
      });
    });
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await chooseTemplate(page);
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();
    await expect(page.getByTestId("hire-provisioning-error")).toBeVisible();
    expect(createRequests).toBe(1);

    const retry = page.getByRole("button", { name: "Start again", exact: true });
    await expect(retry).toBeVisible();

    const startRetry = page.waitForRequest(
      (request) => request.url().includes("/start") && request.method() === "POST",
    );
    await retry.click();
    await startRetry;

    expect(createRequests).toBe(1);
  });

  test("hides the creation form once the Agent exists", async ({ page }) => {
    await dataSupport.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, name: "Aria", status: "STOPPED" },
    });
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await chooseTemplate(page);
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();
    await expect(page.getByTestId("hire-provisioning-error")).toBeVisible();

    // The Agent is persisted with the submitted configuration, so an edit here would
    // promise a change the retry cannot apply.
    await expect(page.getByRole("combobox")).toHaveCount(0);
    await expect(page.getByRole("textbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start again", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeEnabled();
  });
});
