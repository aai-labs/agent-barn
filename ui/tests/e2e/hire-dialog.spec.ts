import { expect, test, type Page } from "@playwright/test";

import { mockAgent, mockVersionsForKey } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import {
  mockPlatformSkill,
  mockCustomSkill,
  mockJiraSkill,
  mockGmailSkill,
  MOCK_PLATFORM_SKILL_ID,
  MOCK_BITBUCKET_SKILL_ID,
} from "../pages/data-support/skill-data-support.po";

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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await page.route("**/api/v1/auth/me/slack-config-token", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ has_token: true, token_preview: "xoxe.****test" }),
        });
      } else {
        await route.fallback();
      }
    });
    await page.route("**/api/v1/organizations/*/slack/apps", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            app_id: "A_TEST_123",
            bot_token_url: "https://api.slack.com/apps/A_TEST_123/install-on-team",
            app_token_url: "https://api.slack.com/apps/A_TEST_123/general",
          }),
        });
      } else {
        await route.fallback();
      }
    });

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("should open the hire dialog on step 1", async ({ page }) => {
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
    await expect(page.getByText(/step 1 of/i)).toBeVisible();
  });

  test("should advance to agent-type step after template", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type

    await expect(page.getByText("Choose your agent runtime")).toBeVisible();
    await expect(page.getByText(/step 2 of/i)).toBeVisible();
  });

  test("should collect Discord identity and routing configuration", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByText("Discord", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → Discord token

    await expect(page.getByText("Connect your Discord bot")).toBeVisible();
    await page.getByPlaceholder("Discord bot token").fill("discord-token");
    await page.getByPlaceholder("123456789012345678").first().fill("111111111111111111");
    await expect(page.getByRole("link", { name: /recommended install link/i })).toHaveAttribute(
      "href",
      /client_id=111111111111111111/,
    );
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByLabel("Name them")).toBeVisible();
  });

  test("should skip bot builder when choosing existing app", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Connect Slack")).toBeVisible();
    await expect(page.getByText(/step 5 of 7/i)).toBeVisible();
  });

  test("should go through bot builder when choosing new bot", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Build your Slack bot")).toBeVisible();
    await expect(page.getByText(/step 5 of 8/i)).toBeVisible();
  });

  test("should show bot builder fields when choosing new bot", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByPlaceholder("Aria")).toBeVisible();
    await expect(page.getByText("Bot display name")).toBeVisible();
  });

  test("should advance to details step (path: skip bot builder)", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("A few details and we'll get them set up.")).toBeVisible();
    await expect(page.getByText(/step 6 of 7/i)).toBeVisible();
  });

  test("should show model dropdown with glm-5.2 as default and gpt-5-mini as option", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click();

    // The model picker is a searchable combobox: the trigger button shows the
    // default model's label, and options render once it is opened.
    const modelTrigger = page.getByRole("button", { name: /model/i });
    await expect(modelTrigger).toBeVisible();
    await expect(modelTrigger).toContainText(/glm 5\.2/i);

    await modelTrigger.click();
    await expect(page.getByRole("option", { name: /glm 5\.2/i })).toBeVisible();
    await expect(page.getByRole("option", { name: /gpt-5 mini/i })).toBeVisible();
  });

  test("should populate agent name from slack bot name", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
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
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
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

  test("should close the hire dialog", async ({ page }) => {
    await page.getByRole("button", { name: /cancel/i }).click();

    await expect(page.getByText("What kind of teammate do you need?")).not.toBeVisible();
  });

  test("template step renders catalog templates with built-in badges and a version dropdown", async ({ page }) => {
    await expect(page.getByText("General Purpose", { exact: true })).toBeVisible();
    await expect(page.getByText("Scrum Master", { exact: true })).toBeVisible();
    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
    // Badge spans only (source filter options are not spans).
    await expect(page.locator('span:text-is("Built-in")')).toHaveCount(2);
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
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
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

  test("details step shows command approval select defaulting to auto", async ({ page }) => {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details

    await expect(page.getByText("Command approval")).toBeVisible();
    await expect(page.locator('label:text-is("Command approval") + select')).toHaveValue("auto");
  });

  test("hire posts approval_mode from details step selection", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await dataSupportPage.agents.interceptSlackChannelsRequest({ agentId: mockAgent.id });
    await dataSupportPage.agents.interceptSlackUsersRequest({ agentId: mockAgent.id });

    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.locator('label:text-is("Command approval") + select').selectOption("manual");
    await page.getByRole("button", { name: /continue/i }).click(); // details → skills

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/agents$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Aria" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as Record<string, unknown>;

    expect(body.approval_mode).toBe("manual");
  });

  test("hire posts template_key + selected version, not markdown", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await dataSupportPage.agents.interceptSlackChannelsRequest({ agentId: mockAgent.id });
    await dataSupportPage.agents.interceptSlackUsersRequest({ agentId: mockAgent.id });

    // Select general-purpose, then pick v1 (default is latest v2) to prove the chosen version is submitted.
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByLabel("Version").click();
    await page.getByRole("menuitemradio", { name: "v1" }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.getByRole("button", { name: /continue/i }).click(); // details → skills

    await expect(page.getByText("Assign skills")).toBeVisible();

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/agents$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Aria" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as Record<string, unknown>;

    // Markdown never leaves the backend — only slug + version are submitted.
    expect(body.template_key).toBe("general-purpose");
    expect(body.template_version).toBe(1);
    expect(body.soul_md).toBeUndefined();
    expect(body.identity_md).toBeUndefined();
  });
});

test.describe("Hire Dialog — Skills step", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupportPage: DataSupport;
  let dashboardPage: DashboardPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  async function navigateToSkillsStep(page: Page) {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.getByRole("button", { name: /continue/i }).click(); // details → skills
  }

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await page.route("**/api/v1/auth/me/slack-config-token", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ has_token: true, token_preview: "xoxe.****test" }),
        });
      } else {
        await route.fallback();
      }
    });

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("shows Assign skills title and correct step number", async ({ page }) => {
    await navigateToSkillsStep(page);

    await expect(page.getByText("Assign skills")).toBeVisible();
    await expect(page.getByText(/step 7 of 7/i)).toBeVisible();
  });

  test("shows skills as cards with source badges and search input", async ({ page }) => {
    await navigateToSkillsStep(page);

    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByText(mockCustomSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder("Search skills…")).toBeVisible();
  });

  test("search filters skills", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByPlaceholder("Search skills…").fill(mockCustomSkill.name);
    await expect(page.getByText(mockCustomSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).not.toBeVisible();
  });

  test("shows empty state when no skills are available", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillsRequest({ body: [] });

    await navigateToSkillsStep(page);

    await expect(page.getByText(/No skills available/)).toBeVisible();
    await expect(page.getByText(/Settings.*Skills/)).toBeVisible();
  });

  test("selecting a skill with required providers reveals credentials section", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();

    await expect(page.getByText("Required credentials", { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();
  });

  test("hire button is disabled when selected skill has incomplete credentials", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();

    // GitHub requires token + owner; both empty → button disabled
    await expect(page.getByRole("button", { name: /hire aria/i })).toBeDisabled();
  });

  test("hire button is enabled when no skills are selected", async ({ page }) => {
    await navigateToSkillsStep(page);

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeEnabled();
  });

  test("deselecting a skill removes its credentials section", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();
    await expect(page.getByText("Required credentials", { exact: true })).toBeVisible();

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();
    await expect(page.getByText("Required credentials", { exact: true })).not.toBeVisible();
  });

  test("hire button enables with token + owner filled and no repositories added", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();
    await page.getByPlaceholder(/github_pat_/).fill("ghp_test_token");
    await page.getByPlaceholder("owner-or-org").fill("acme");

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeEnabled();
  });

  test("repositories field adds and removes chips without affecting required-field gating", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();
    await page.getByPlaceholder(/github_pat_/).fill("ghp_test_token");
    await page.getByPlaceholder("owner-or-org").fill("acme");

    const repoInput = page.getByPlaceholder("repository name");
    await repoInput.fill("repo-a");
    await repoInput.press("Enter");
    await repoInput.fill("repo-b");
    await page.getByRole("button", { name: "Add" }).click();

    await expect(page.getByText("repo-a", { exact: true })).toBeVisible();
    await expect(page.getByText("repo-b", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Remove repo-a" }).click();
    await expect(page.getByText("repo-a", { exact: true })).not.toBeVisible();
    await expect(page.getByText("repo-b", { exact: true })).toBeVisible();

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeEnabled();
  });

  test("submits multiple repository names in the github secret content", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });

    await navigateToSkillsStep(page);
    await page.getByText(mockPlatformSkill.name, { exact: true }).click();
    await page.getByPlaceholder(/github_pat_/).fill("ghp_test_token");
    await page.getByPlaceholder("owner-or-org").fill("acme");

    const repoInput = page.getByPlaceholder("repository name");
    await repoInput.fill("repo-a");
    await repoInput.press("Enter");
    await repoInput.fill("repo-b");
    await repoInput.press("Enter");

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/agents$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Aria" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as {
      secrets: Array<{ provider: string; content: Record<string, unknown> }>;
    };

    const githubSecret = body.secrets.find((s) => s.provider === "github");
    expect(githubSecret?.content.owner).toBe("acme");
    expect(githubSecret?.content.org).toBe("acme");
    expect(githubSecret?.content.repos).toEqual(["repo-a", "repo-b"]);
  });

  test("selecting a jira skill reveals jira credential fields", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockJiraSkill.name, { exact: true }).click();

    await expect(page.getByText("Required credentials", { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/atlassian\.net/)).toBeVisible();
    await expect(page.getByText("Authentication Type")).toBeVisible();

    // Email field is always visible — scoped and non-scoped tokens both use Basic Auth
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
  });

  test("hire button is disabled when jira credentials are incomplete", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockJiraSkill.name, { exact: true }).click();

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeDisabled();
  });

  test("automatic Slack credentials do not block hiring", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [
          {
            id: mockJiraSkill.id,
            name: "jira",
            source: "aai_cli",
            required_providers: ["jira"],
            tools_pointer: null,
            required: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          {
            id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
            name: "slack",
            source: "aai_cli",
            required_providers: ["slack"],
            tools_pointer: null,
            required: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      })),
    });

    await navigateToSkillsStep(page);

    await expect(page.getByText(/Slack — uses this agent's existing Slack bot token automatically/)).toBeVisible();
    await page.getByPlaceholder(/atlassian\.net/).fill("https://aai-labs.atlassian.net/");
    await page.getByRole("radio", { name: "Scoped token", exact: true }).check();
    await page.getByPlaceholder("you@example.com").fill("kalkidan@aai-labs.com");
    await page.locator('input[type="password"]').last().fill("jira-api-token");

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/agents$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await expect(page.getByRole("button", { name: /hire aria/i })).toBeEnabled();
    await page.getByRole("button", { name: "Hire Aria" }).click();

    const body = (await createPromise).postDataJSON() as {
      secrets: Array<{ provider: string }>;
    };
    expect(body.secrets.some((secret) => secret.provider === "slack")).toBe(false);
  });

  test("selecting a gmail skill reveals the Google OAuth button", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockGmailSkill.name, { exact: true }).click();

    await expect(page.getByText("Required credentials", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Authenticate with Google" })).toBeVisible();
  });

  test("hire button is disabled when gmail credentials are incomplete", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText(mockGmailSkill.name, { exact: true }).click();

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeDisabled();
  });

  test("required skill card is shown as locked-selected with 'Required by template' label", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await navigateToSkillsStep(page);

    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByText("Required by template")).toBeVisible();
  });

  test("clicking a required skill card does not deselect it", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await navigateToSkillsStep(page);

    await page.getByText(mockPlatformSkill.name, { exact: true }).click();

    await expect(page.getByText("Required by template")).toBeVisible();
  });

  test("credential form appears for required skill provider without selecting the skill", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await navigateToSkillsStep(page);

    await expect(page.getByText("Required credentials", { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();
  });

  test("hire button is disabled when required skill credentials are incomplete", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await navigateToSkillsStep(page);

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeDisabled();
  });
});

test.describe("Hire Dialog — Skills step required skill group", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupportPage: DataSupport;
  let dashboardPage: DashboardPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  const GROUP_KEY = "github-or-bitbucket";

  async function navigateToSkillsStep(page: Page) {
    await page.getByText("General Purpose", { exact: true }).click();
    await page.getByRole("button", { name: /continue/i }).click(); // template → agent-type
    await page.getByRole("button", { name: /continue/i }).click(); // agent-type → platform-choice
    await page.getByRole("button", { name: /continue/i }).click(); // platform-choice → slack-choice
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click(); // slack-choice → tokens
    await page.getByPlaceholder(/xapp-/i).fill("xapp-1-test");
    await page.getByPlaceholder(/xoxb-/i).fill("xoxb-test");
    await page.getByRole("button", { name: /continue/i }).click(); // tokens → details
    await page.getByRole("button", { name: /continue/i }).click(); // details → skills
  }

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("general-purpose").map((v) => ({
        ...v,
        required_skills: [
          {
            id: MOCK_PLATFORM_SKILL_ID,
            name: "github",
            source: "aai_cli",
            required_providers: ["github"],
            tools_pointer: null,
            required: false,
            group_key: GROUP_KEY,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          {
            id: MOCK_BITBUCKET_SKILL_ID,
            name: "bitbucket",
            source: "aai_cli",
            required_providers: ["bitbucket"],
            tools_pointer: null,
            required: false,
            group_key: GROUP_KEY,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      })),
    });
    await page.route("**/api/v1/auth/me/slack-config-token", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ has_token: true, token_preview: "xoxe.****test" }),
        });
      } else {
        await route.fallback();
      }
    });

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire agent/i }).click();
  });

  test("renders a choose-at-least-one section with both group members", async ({ page }) => {
    await navigateToSkillsStep(page);

    await expect(page.getByText(/Required by template — choose at least one/i)).toBeVisible();
    await expect(page.getByText("github", { exact: true })).toBeVisible();
    await expect(page.getByText("bitbucket", { exact: true })).toBeVisible();
  });

  test("hire button stays disabled until a group choice is made", async ({ page }) => {
    await navigateToSkillsStep(page);

    await expect(page.getByRole("button", { name: /hire aria/i })).toBeDisabled();

    await page.getByText("github", { exact: true }).click();

    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();
  });

  test("choosing GitHub shows only the GitHub credential form", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText("github", { exact: true }).click();

    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();
    await expect(page.getByPlaceholder("owner-or-org")).toBeVisible();
  });

  test("selecting a second group member adds its credential form alongside the first", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText("github", { exact: true }).click();
    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();

    await page.getByText("bitbucket", { exact: true }).click();

    // Both hosts chosen — both credential forms render.
    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();
    await expect(page.getByPlaceholder("workspace id")).toBeVisible();
  });

  test("clicking a chosen group member again deselects it and removes its credential form", async ({ page }) => {
    await navigateToSkillsStep(page);

    await page.getByText("github", { exact: true }).click();
    await expect(page.getByPlaceholder(/github_pat_/)).toBeVisible();

    await page.getByText("github", { exact: true }).click();

    await expect(page.getByPlaceholder(/github_pat_/)).not.toBeVisible();
  });

  test("created agent request includes only the chosen group member in skill_ids", async ({ page }) => {
    await dataSupportPage.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });

    await navigateToSkillsStep(page);
    await page.getByText("bitbucket", { exact: true }).click();

    await page.getByPlaceholder("workspace id").fill("acme-workspace");
    await page.getByPlaceholder("you@example.com").fill("me@example.com");
    // apiToken is the only password-type field once Bitbucket (not GitHub) is chosen.
    await page.locator('input[type="password"]').fill("bb-token");

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/agents$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Hire Aria" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as { skill_ids: string[] };

    expect(body.skill_ids).toContain(MOCK_BITBUCKET_SKILL_ID);
    expect(body.skill_ids).not.toContain(MOCK_PLATFORM_SKILL_ID);
  });
});
