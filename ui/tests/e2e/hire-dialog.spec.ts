import { expect, test } from "@playwright/test";

import { mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

test.describe("Hire Dialog", () => {
  test.describe.configure({ mode: "serial" });
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest();

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("should open the hire dialog on step 1", async ({ page }) => {
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
    await expect(page.getByText(/step 1 of/i)).toBeVisible();
  });

  test("should advance to agent-type step", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Choose your agent runtime")).toBeVisible();
    await expect(page.getByText(/step 2 of/i)).toBeVisible();
  });

  test("should advance to platform choice step when OpenClaw is selected", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("OpenClaw").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Choose your platform")).toBeVisible();
    await expect(page.getByText(/step 3 of/i)).toBeVisible();
  });

  test("should skip platform choice for hermes and go directly to slack setup", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type (hermes default)
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice

    await expect(page.getByText("Set up your Slack app")).toBeVisible();
    await expect(page.getByText(/step 3 of/i)).toBeVisible();
  });

  test("should skip bot builder when choosing existing app", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Connect Slack")).toBeVisible();
    await expect(page.getByText(/step 4 of 6/i)).toBeVisible();
  });

  test("should go through bot builder when choosing new bot", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Build your Slack bot")).toBeVisible();
    await expect(page.getByText(/step 4 of 7/i)).toBeVisible();
  });

  test("should show manifest in bot builder step", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Generated manifest")).toBeVisible();
    await expect(page.getByRole("link", { name: /create app/i })).toBeVisible();
  });

  test("should advance to details step (path: skip bot builder)", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("A few details and we'll get them set up.")).toBeVisible();
    await expect(page.getByText(/step 5 of 6/i)).toBeVisible();
  });

  test("should show model dropdown with qwen as default and gpt-5-mini as option", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByRole("combobox", { name: /model/i })).toBeVisible();
    await expect(page.getByRole("combobox", { name: /model/i })).toHaveValue("litellm/qwen3.6-plus");
    await expect(page.getByRole("option", { name: /qwen3\.6 plus/i })).toBeAttached();
    await expect(page.getByRole("option", { name: /gpt-5 mini/i })).toBeAttached();
  });

  test("should populate agent name from slack bot name", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await page.getByPlaceholder("Aria").clear();
    await page.getByPlaceholder("Aria").fill("My Slack Bot");
    await page.getByRole("button", { name: /continue/i }).click();

    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByLabel("Name them")).toHaveValue("My Slack Bot");
  });

  test("should show Slack config panel after hiring and call start on skip", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await dataSupportPage.agents.interceptStartAgentRequest({ agentId: mockAgent.id });
    await dataSupportPage.agents.interceptSlackChannelsRequest({ agentId: mockAgent.id });
    await dataSupportPage.agents.interceptSlackUsersRequest({ agentId: mockAgent.id });

    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.getByRole("button", { name: /continue/i }).click(); // details → integrations
    await page.getByRole("button", { name: "Hire Aria" }).click();

    await expect(page.getByText("Set up Slack access")).toBeVisible();

    const startPromise = page.waitForRequest((req) =>
      req.url().includes("/start") && req.method() === "POST"
    );
    await page.getByRole("button", { name: /skip for now/i }).click();
    await startPromise;
  });

  test("should navigate back through steps", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page.getByText("Choose your agent runtime")).toBeVisible();

    await page.getByRole("button", { name: /back/i }).click();
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
  });

  test("should collect Teams credentials before package generation", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByText("OpenClaw").click();
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByText("Microsoft Teams").click();
    await page.getByRole("button", { name: /continue/i }).click(); // platform → teams-credentials

    await expect(page.getByText("Connect to Azure")).toBeVisible();
    await expect(page.getByText(/step 4 of 7/i)).toBeVisible();
    await expect(page.getByText("Azure credentials")).toBeVisible();
    await expect(page.getByText("Create an Azure Bot resource", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /continue/i }).click();
    await expect(
      page.getByText("App ID, App Password, and Tenant ID are all required."),
    ).toBeVisible();

    await page.getByPlaceholder(/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/i).nth(0).fill(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    await page.getByPlaceholder("Client secret value").fill("secret-value");
    await page.getByPlaceholder(/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/i).nth(1).fill(
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Build your Teams bot")).toBeVisible();
    await expect(page.getByText(/step 5 of 7/i)).toBeVisible();
    await page.getByPlaceholder("Aria").fill("Sam");
    await expect(page.getByText("Teams app package", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /download teams app package/i })).toBeVisible();
    await expect(page.getByText('"developer"')).toBeVisible();
    await expect(page.getByText('"botId"')).toBeVisible();
    await expect(page.getByText('"color": "color.png"')).toBeVisible();
    await expect(page.getByText('"outline": "outline.png"')).toBeVisible();
    await expect(page.getByText("Upload to Teams")).toBeVisible();

    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page.getByText("A few details and we'll get them set up.")).toBeVisible();
    await expect(page.getByLabel("Name them")).toHaveValue("Sam");
  });

  test("should close the hire dialog", async ({ page }) => {
    await page.getByRole("button", { name: /cancel/i }).click();

    await expect(page.getByText("What kind of teammate do you need?")).not.toBeVisible();
  });

  test("template step renders catalog templates with pre-defined badges and a version dropdown", async ({ page }) => {
    await expect(page.getByText("General Purpose", { exact: true })).toBeVisible();
    await expect(page.getByText("Scrum Master", { exact: true })).toBeVisible();
    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
    // Badge spans only (source filter options are not spans).
    await expect(page.locator('span:text-is("Pre-defined")')).toHaveCount(2);
    // Select a template to reveal the version dropdown.
    await page.getByText("General Purpose", { exact: true }).click();
    const version = page.getByLabel("Version");
    await expect(version).toBeVisible();
    await expect(version).toContainText("v2");
  });

  test("details step shows a read-only template preview with raw placeholders", async ({ page }) => {
    // Pick the scrum-master template (its soul contains a raw {{ placeholder }}).
    await page.getByText("Scrum Master", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details

    await page.getByText("Review configuration files").click();
    const preview = page.getByLabel("SOUL.md preview");
    await expect(preview).toBeVisible();
    await expect(preview).toHaveAttribute("readonly", "");
    await expect(preview).toHaveValue(/\{\{ agent_display_name \}\}/);
  });

  test("hire posts template_slug + selected version, not markdown", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await dataSupportPage.agents.interceptSlackChannelsRequest({ agentId: mockAgent.id });
    await dataSupportPage.agents.interceptSlackUsersRequest({ agentId: mockAgent.id });

    // Select general-purpose, then pick v1 (default is latest v2) to prove the chosen version is submitted.
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByLabel("Version").click();
    await page.getByRole("menuitemradio", { name: "v1" }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.getByRole("button", { name: /continue/i }).click(); // details → integrations

    const createPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/agents") && req.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Aria" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as Record<string, unknown>;

    // Markdown never leaves the backend — only slug + version are submitted.
    expect(body.template_slug).toBe("general-purpose");
    expect(body.template_version).toBe(1);
    expect(body.soul_md).toBeUndefined();
    expect(body.identity_md).toBeUndefined();
  });
});
