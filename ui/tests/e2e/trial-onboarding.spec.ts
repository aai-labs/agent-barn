import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  agentReady,
  TRIAL_AGENT_ID,
  onboarding,
  TRIAL_DEEP_LINK,
  TRIAL_FRESH_DEEP_LINK,
  TRIAL_ORG_ID,
  trialUserContext,
} from "../pages/data-support/onboarding-data-support.po";
import { mockAgent, mockAssignedSkill, mockTemplates } from "../pages/data-support/agent-data-support.po";
import { mockPlatformSkill } from "../pages/data-support/skill-data-support.po";
import { OnboardingPage } from "../pages/onboarding-page.po";
import { DashboardPage } from "../pages/dashboard-page.po";

const linkedAccount = {
  id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
  telegram_username: "jane_doe",
  linked_by_membership_id: "11111111-1111-4111-8111-111111111111",
  created_at: "2026-10-07T12:01:00Z",
};

async function signedInTrialUser(page: Page) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
  await data.users.interceptGetOrganizationsRequest();
  await data.organizations.interceptGetOrganization({ organization: trialUserContext.organization_users[0].organization });
  return data;
}

test.describe("Trial sign-in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    await new DataSupport(page).auth.interceptLogoutRequest();
  });

  test("the welcome screen shows Google and password login by default", async ({ page }) => {
    const onboardingPage = new OnboardingPage(page);
    await onboardingPage.gotoSignup();

    await expect(onboardingPage.heading("Welcome to Agent Barn")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveCount(0);
    await expect(page.getByLabel("Email", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
    await expect(onboardingPage.continueWithGoogle()).toHaveAttribute(
      "href",
      "/api/v1/auth/google/start?origin=signup",
    );
  });

  const errors: [string, RegExp][] = [
    ["cancelled", /Google sign-in was cancelled\. Nothing was created\./],
    ["failed", /Google sign-in didn.t work\. Nothing was created\./],
    ["unavailable", /Google sign-in isn.t available right now/],
    ["unverified", /Google hasn.t verified the email address/],
    ["signup_closed", /Sign-up is closed right now/],
    ["trial_used", /This email has already had a free trial/],
    ["trials_full", /We.ve reached our limit of free trials for now\. Try again later\./],
    // Not one of ours: falls back to the generic failure, never an empty alert.
    ["constructor", /Google sign-in didn.t work\. Nothing was created\./],
  ];
  for (const [code, message] of errors) {
    test(`a ${code} sign-in says so and offers Google again`, async ({ page }) => {
      const onboardingPage = new OnboardingPage(page);
      await onboardingPage.gotoSignup(code);

      await expect(onboardingPage.alert()).toHaveText(message);
      await expect(onboardingPage.continueWithGoogle()).toBeVisible();
    });
  }

  test("the login page also signs in with Google, and shows why it failed", async ({ page }) => {
    await page.goto("/login?error=cancelled");

    await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveAttribute(
      "href",
      "/api/v1/auth/google/start?origin=login",
    );
    await expect(new OnboardingPage(page).alert()).toHaveText(/Google sign-in was cancelled/);
    await expect(page.getByLabel("Email", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  });
});

test.describe("Trial onboarding", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("explains the account wait and opens choices as soon as it is ready", async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 320, height: 740 });
    const data = await signedInTrialUser(page);
    const release = await data.onboarding.holdOnboardingResponse();
    const setups = await data.onboarding.interceptSetUpAgent();
    try {
      await page.goto("/onboarding");
      await expect(page.getByRole("status")).toContainText("We're loading your account and checking where you left off.");
      await expect(page.getByText("Start with a ready-made assistant, or build an agent your way.")).toBeVisible();
      await expect(page.getByText("Signed in. We'll take it from here.")).toBeVisible();
      for (const width of [320, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 800 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        if (width === 320 || width === 1440) {
          await testInfo.attach(`account-opening-${width}`, { body: await page.screenshot(), contentType: "image/png" });
        }
      }
      expect(setups).toHaveLength(0);
    } finally {
      release();
    }
    await expect(new OnboardingPage(page).heading("How do you want to start?")).toBeVisible();
    await expect(page.getByRole("status")).toHaveCount(0);
    expect(setups).toHaveLength(0);
  });

  test("opening the choice screen creates no agent", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const calls = await data.onboarding.interceptSetUpAgent();
    await page.goto("/onboarding");
    await expect(new OnboardingPage(page).heading("How do you want to start?")).toBeVisible();
    expect(calls).toHaveLength(0);
  });

  for (const screen of ["choice", "custom setup"]) {
    test(`can defer ${screen} without hiring an agent`, async ({ page }) => {
      const data = await signedInTrialUser(page);
      await data.onboarding.interceptGetOnboarding();
      const creations = data.onboarding.trackAgentCreationRequests();
      const completions = await data.onboarding.interceptCompleteOnboarding([204], { required: false });
      await data.agents.interceptGetTemplatesRequest();
      await data.agents.interceptGetModelsRequest();
      await data.agents.interceptNameSuggestionRequest();
      const wizard = new OnboardingPage(page);
      await wizard.goto();
      if (screen === "custom setup") await wizard.chooseOwnAgent();
      await wizard.laterAction().click();
      await expect(page).toHaveURL(`/dashboard/${TRIAL_ORG_ID}`);
      expect(completions).toHaveLength(1);
      expect(creations).toHaveLength(0);
      await page.goto("/onboarding");
      await expect(page).toHaveURL(`/dashboard/${TRIAL_ORG_ID}`);
    });
  }

  test("deferring setup can retry a failed save without hiring an agent", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const creations = data.onboarding.trackAgentCreationRequests();
    const completions = await data.onboarding.interceptCompleteOnboarding([500, 204], { required: false });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.laterAction().click();
    await expect(wizard.alert()).toContainText("save your progress");
    await wizard.retryAction().click();
    await expect(page).toHaveURL(`/dashboard/${TRIAL_ORG_ID}`);
    expect(completions).toHaveLength(2);
    expect(creations).toHaveLength(0);
  });

  test("builds a custom agent without consuming a quick-start slot", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const setups = await data.onboarding.interceptSetUpAgent();
    const completions = await data.onboarding.interceptCompleteOnboarding([204], {
      required: false,
      completed_at: "2026-10-14T12:00:00Z",
    });
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.agents.interceptCreateAgentRequest({ body: { ...mockAgent, id: TRIAL_AGENT_ID, name: "My helper", status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ agentId: TRIAL_AGENT_ID });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseOwnAgent();
    await wizard.agentName().fill("My helper");
    await wizard.template().click();
    await wizard.hireAction().click();
    await expect(wizard.heading("Let your agent read your Gmail")).toBeVisible();
    await wizard.skipGmail().click();
    await expect(wizard.heading("My helper is ready")).toBeVisible();
    expect(setups).toHaveLength(0);
    expect(completions).toHaveLength(1);
    await expect(page.getByRole("link", { name: "Chat with your agent" })).toHaveAttribute("href", `/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`);
    await expect(page.getByRole("link", { name: "Connect a messaging app", exact: true })).toHaveAttribute("href", `/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}/configuration?section=channels&connect=true`);
    await expect(page.getByRole("link", { name: "Connect Telegram", exact: true })).toHaveCount(0);
  });

  test("retrying completion does not create or start the agent again", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const setups = await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts([linkedAccount]);
    const completions = await data.onboarding.interceptCompleteOnboarding([500, 204]);
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    await wizard.continueAction().click();
    await wizard.skipGmail().click();
    await expect(wizard.alert()).toContainText("save your progress");
    await wizard.retryAction().click();
    await expect(wizard.heading("Your agent is live in Telegram.")).toBeVisible();
    expect(setups).toHaveLength(1);
    expect(completions).toHaveLength(2);
  });

  test("completion stays ready when the server retires onboarding details", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts([linkedAccount]);
    await data.onboarding.interceptCompleteOnboarding([204], {
      required: false,
      completed_at: "2026-10-14T12:00:00Z",
    });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    const completedRead = page.waitForResponse(async (response) =>
      response.url().endsWith("/api/v1/onboarding") && (await response.json()).required === false,
    );
    await wizard.continueAction().click();
    await wizard.skipGmail().click();
    await completedRead;
    await expect(wizard.heading("Your agent is live in Telegram.")).toBeVisible();
    await expect(wizard.summaryRow("credit")).toContainText("$10.00");
    await expect(wizard.openTelegram()).toHaveAttribute("href", "https://t.me/AgentBarnTestBot");
    await wizard.goToDashboard().click();
    await expect(page).toHaveURL(`/dashboard/${TRIAL_ORG_ID}`);
  });

  test("linking from a QR scan is detected without opening the browser link", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens({ statuses: ["waiting", "linked"] });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    await expect(page.getByText("Linked as @jane_doe")).toBeVisible();
    await expect(wizard.continueAction()).toBeVisible();
  });

  test("custom setup can hire template 51 and preserves its selection while browsing API pages", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptCompleteOnboarding();
    const templates = Array.from({ length: 54 }, (_, index) => ({
      ...mockTemplates[0], template_key: `template-${index + 1}`, template_name: `Template ${index + 1}`,
      description: "A useful assistant for multi-page onboarding catalogs.",
      required_skills: index === 50 ? [{ ...mockAssignedSkill, id: mockPlatformSkill.id, required: true, version: 3 }] : [],
    }));
    await data.agents.interceptGetTemplatesRequest({ catalog: templates });
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.skills.interceptGetSkillsRequest();
    await data.agents.interceptCreateAgentRequest({ body: { ...mockAgent, id: TRIAL_AGENT_ID, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ agentId: TRIAL_AGENT_ID });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseOwnAgent();
    for (let pageIndex = 0; pageIndex < 8; pageIndex += 1) await wizard.nextTemplates().click();
    const template = wizard.templateGroup().getByRole("radio", { name: /^Template 51 / });
    await expect(template).toBeVisible();
    await expect(page.getByText("49–54 of 54 templates")).toBeVisible();
    await expect(wizard.nextTemplates()).toBeDisabled();
    await template.click();
    await page.getByPlaceholder("github_pat_… or ghp_…").fill("test-github-token");
    await page.getByPlaceholder("owner-or-org").fill("demo-org");
    await expect(wizard.agentName()).toHaveValue("Brandon the Template 51");
    await wizard.previousTemplates().click();
    await expect(page.getByText("Selected: Template 51", { exact: true })).toBeVisible();
    await expect(wizard.agentName()).toHaveValue("Brandon the Template 51");
    await expect(page.getByPlaceholder("github_pat_… or ghp_…")).toHaveValue("test-github-token");
    await expect(page.getByPlaceholder("owner-or-org")).toHaveValue("demo-org");
    const created = page.waitForRequest((request) => request.url().endsWith("/agents") && request.method() === "POST");
    await wizard.hireAction().click();
    expect((await created).postDataJSON()).toMatchObject({
      name: "Brandon the Template 51", template_key: "template-51", template_version: 1,
      skill_ids: [mockPlatformSkill.id], skill_versions: [{ skill_id: mockPlatformSkill.id, version: 3 }],
      secrets: [{ provider: "github", content: { token: "test-github-token", owner: "demo-org", org: "demo-org" } }],
    });
    await wizard.skipGmail().click();
    await expect(wizard.heading("Maya is ready")).toBeVisible();
  });

  for (const width of [320, 768, 1024, 1440]) {
    test(`wizard fits a ${width}px viewport`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const data = await signedInTrialUser(page);
      await data.onboarding.interceptGetOnboarding();
      const templates = Array.from({ length: 20 }, (_, index) => ({
        ...mockTemplates[0],
        template_key: `template-${index}`,
        template_name: `Template ${index + 1}`,
        description: "An assistant that helps your team organize projects, review documents, and follow up on the work that matters most.",
      }));
      await data.agents.interceptGetTemplatesRequest({ catalog: templates });
      await data.agents.interceptGetModelsRequest();
      await data.agents.interceptNameSuggestionRequest();
      const wizard = new OnboardingPage(page);
      await wizard.goto();
      await expect(wizard.heading("How do you want to start?")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await wizard.chooseOwnAgent();
      await expect(wizard.agentName()).toBeVisible();
      await expect(wizard.templateGroup().getByRole("radio")).toHaveCount(6);
      expect(await wizard.templateGroup().evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
      await expect(wizard.previousTemplates()).toBeDisabled();
      await expect(page.getByText("1–6 of 20 templates")).toBeVisible();
      await wizard.nextTemplates().click();
      await wizard.nextTemplates().click();
      await wizard.nextTemplates().click();
      await expect(wizard.templateGroup().getByRole("radio")).toHaveCount(2);
      await expect(page.getByText("19–20 of 20 templates")).toBeVisible();
      await expect(wizard.nextTemplates()).toBeDisabled();
      const lastTemplate = wizard.templateGroup().getByRole("radio", { name: /^Template 20 / });
      await lastTemplate.click();
      await expect(lastTemplate).toBeChecked();
      await wizard.previousTemplates().click();
      await expect(page.getByText("Selected: Template 20", { exact: true })).toBeVisible();
      await wizard.nextTemplates().click();
      await expect(lastTemplate).toBeChecked();
      await wizard.laterAction().scrollIntoViewIfNeeded();
      await expect(wizard.laterAction()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }

  test("quick start can skip Telegram, then Gmail, and open web chat", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens();
    const completions = await data.onboarding.interceptCompleteOnboarding();
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    await wizard.skipAction().click();
    await expect(wizard.heading("Let your agent read your Gmail")).toBeVisible();
    expect(completions).toHaveLength(0);
    await wizard.skipGmail().click();
    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`);
    expect(completions).toHaveLength(1);
  });

  test("sets up the agent, links Telegram, and finishes", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const setUps = await data.onboarding.interceptSetUpAgent();
    const linked = await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens({ statuses: ["waiting", "waiting", "linked"] });
    const completions = await data.onboarding.interceptCompleteOnboarding();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();

    await expect(onboardingPage.heading("Say hi to @AgentBarnTestBot")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 3 of 5");
    await expect(onboardingPage.openInTelegram()).toHaveAttribute("href", TRIAL_DEEP_LINK);
    await expect(onboardingPage.openInTelegram()).toHaveAttribute("target", "_blank");
    expect(setUps).toHaveLength(1);

    linked.set([linkedAccount]);
    await onboardingPage.openInTelegram().click();
    await expect(page.getByText("Linked as @jane_doe")).toBeVisible();

    await onboardingPage.continueAction().click();

    await expect(onboardingPage.heading("Let your agent read your Gmail")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 4 of 5");
    expect(completions).toHaveLength(0);
    await onboardingPage.skipGmail().click();

    await expect(onboardingPage.heading("Your agent is live in Telegram.")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 5 of 5");
    expect(completions).toHaveLength(1);
    await expect(onboardingPage.summaryRow("account")).toContainText("jane@example.com");
    await expect(onboardingPage.summaryRow("telegram")).toContainText("@jane_doe");
    await expect(onboardingPage.summaryRow("credit")).toContainText("$10.00");
    await expect(onboardingPage.openTelegram()).toHaveAttribute("href", "https://t.me/AgentBarnTestBot");
  });

  test("a link that expired is replaced with a fresh one", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding(agentReady));
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens({
      urls: [TRIAL_DEEP_LINK, TRIAL_FRESH_DEEP_LINK],
      statuses: ["waiting", "expired"],
    });
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();
    await onboardingPage.openInTelegram().click();

    await expect(onboardingPage.alert()).toHaveText(/That link expired after 10 minutes\. Here.s a fresh one\./);
    await expect(page.getByRole("link", { name: "Open in Telegram again" })).toHaveAttribute(
      "href",
      TRIAL_FRESH_DEEP_LINK,
    );
  });

  test("an unopened expired link is refreshed without an expiry warning", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens({
      urls: [TRIAL_DEEP_LINK, TRIAL_FRESH_DEEP_LINK], statuses: ["waiting", "expired"],
    });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    await expect(wizard.openInTelegram()).toHaveAttribute("href", TRIAL_FRESH_DEEP_LINK);
    await expect(wizard.alert()).toHaveCount(0);
    await expect(wizard.openInTelegram()).toHaveText("Open in Telegram");
  });

  for (const source of ["token", "accounts"] as const) {
    test(`Telegram account polling stops after linking through ${source}`, async ({ page }) => {
      const data = await signedInTrialUser(page);
      await data.onboarding.interceptGetOnboarding();
      await data.onboarding.interceptSetUpAgent();
      const accounts = await data.onboarding.interceptLinkedAccounts();
      await data.onboarding.interceptLinkTokens({ statuses: source === "token" ? ["waiting", "linked"] : ["waiting"] });
      const wizard = new OnboardingPage(page);
      await wizard.goto();
      await wizard.chooseQuickStart();
      await expect(wizard.openInTelegram()).toBeVisible();
      if (source === "accounts") accounts.set([linkedAccount]);
      await expect(page.getByText("Linked as @jane_doe")).toBeVisible();
      // Allow an in-flight account refresh, then observe two full polling intervals.
      await page.waitForTimeout(500);
      const checks = accounts.checks.length;
      await page.waitForTimeout(4500);
      expect(accounts.checks).toHaveLength(checks);
    });
  }

  test("an agent that failed to start can be retried", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const setUps = await data.onboarding.interceptSetUpAgent([
      onboarding({ ...agentReady, agent_status: "ERROR" }),
      onboarding(agentReady),
    ]);
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();

    await expect(onboardingPage.alert()).toHaveText(/We couldn.t start your agent/);
    await onboardingPage.retryAction().click();

    await expect(onboardingPage.openInTelegram()).toBeVisible();
    expect(setUps).toHaveLength(2);
  });

  test("a setup that fails says why", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgentFailure(400, "Agent Barn Telegram is not available");
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();

    await expect(onboardingPage.alert()).toHaveText(
      /We couldn.t set up your agent: Agent Barn Telegram is not available/,
    );
    await expect(onboardingPage.retryAction()).toBeVisible();
  });

  for (const exit of ["later without Agent", "later with Agent", "Web Chat", "Web Chat after partial setup"] as const) {
    test(`a setup failure allows ${exit}`, async ({ page }) => {
      const data = await signedInTrialUser(page);
      const existing = exit !== "later without Agent";
      const partialSetup = onboarding({ ...agentReady, agent_status: "ERROR", connection_id: null });
      await data.onboarding.interceptGetOnboarding(onboarding(existing && exit !== "Web Chat after partial setup" ? { ...agentReady, agent_status: "ERROR" } : {}));
      await data.onboarding.interceptSetUpAgentFailure(400, "Telegram setup unavailable", exit === "Web Chat after partial setup" ? partialSetup : undefined);
      const completions = await data.onboarding.interceptCompleteOnboarding([500, 204], onboarding({ required: false }));
      const creations = data.onboarding.trackAgentCreationRequests();
      const wizard = new OnboardingPage(page);
      await wizard.goto();
      await wizard.chooseQuickStart();
      await expect(wizard.alert()).toContainText("Telegram setup unavailable");
      await expect(wizard.laterAction()).toBeVisible();
      await expect(wizard.skipAction()).toHaveCount(existing ? 1 : 0);
      const chat = exit.startsWith("Web Chat");
      const action = chat ? wizard.skipAction() : wizard.laterAction();
      await action.click();
      await expect(wizard.alert().filter({ hasText: /save your progress/ })).toBeVisible();
      if (chat) await action.click();
      else await wizard.retryAction().click();
      await expect(page).toHaveURL(chat
        ? `/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`
        : `/dashboard/${TRIAL_ORG_ID}`);
      expect(completions).toHaveLength(2);
      expect(creations).toHaveLength(1);
    });
  }

  test("someone already linked goes straight to Continue", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding(agentReady));
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts([linkedAccount]);
    await data.onboarding.interceptLinkTokens();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();

    await expect(page.getByText("Linked as @jane_doe")).toBeVisible();
    await expect(onboardingPage.continueAction()).toBeVisible();
  });

  test("Go to dashboard opens the trial organization", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding(agentReady));
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts([linkedAccount]);
    await data.onboarding.interceptLinkTokens();
    await data.onboarding.interceptCompleteOnboarding();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();
    await onboardingPage.chooseQuickStart();
    await onboardingPage.continueAction().click();
    await onboardingPage.skipGmail().click();
    await expect(onboardingPage.goToDashboard()).toHaveClass(/\baf-btn-primary\b/);
    await expect(onboardingPage.openTelegram()).not.toHaveClass(/\baf-btn-primary\b/);
    await expect(onboardingPage.openTelegram()).toHaveAttribute("target", "_blank");
    await expect(onboardingPage.openTelegram()).toHaveAttribute("href", "https://t.me/AgentBarnTestBot");
    await onboardingPage.goToDashboard().click();

    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}`);
  });

  test("a finished user who opens onboarding lands on the dashboard", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false, completed_at: "2026-10-07T12:05:00Z" }));
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto("/onboarding");

    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}`);
  });

  test("a trial user who hasn't finished is sent from the dashboard to onboarding", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens();

    await page.goto("/dashboard");

    await page.waitForURL("/onboarding");
  });

  test("a trial under its agent limit can hire", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, agent_limit: 50, agent_limit_reached: false, trial_agent_limit: 50, trial_agent_limit_reached: false },
    });
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    const dashboard = new DashboardPage(page);
    await dashboard.openHireChoices();
    await dashboard.chooseCustomHiring();

    await expect(page.getByLabel("Agent name")).toBeVisible();
  });

  test("once the trial has ended, its owner can create organizations", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    const ended = { ...structuredClone(trialUserContext), trial_ended_at: "2026-10-08T09:00:00Z" };
    ended.organization_users[0].organization.is_trial = false;
    await data.users.interceptGetUserContextRequest({ userContext: ended });
    await data.users.interceptGetOrganizationsRequest();
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: /Jane's Organization/ }).first().click();

    await expect(page.getByRole("menuitem", { name: "Create organization" })).toBeVisible();
  });

  test("deleting the trial doesn't let its owner create organizations", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    const otherOrg = { ...trialUserContext.organization_users[0], role: "MEMBER" };
    otherOrg.organization = { ...otherOrg.organization, name: "Someone's Team", is_trial: false };
    await data.users.interceptGetUserContextRequest({
      userContext: { ...trialUserContext, organization_users: [otherOrg] },
    });
    await data.users.interceptGetOrganizationsRequest();
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: /Someone's Team/ }).first().click();

    await expect(page.getByRole("menuitem", { name: "Create organization" })).toHaveCount(0);
  });

  test("a trial user can't create another organization", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: /Jane's Organization/ }).first().click();

    await expect(page.getByRole("menuitem", { name: "Create organization" })).toHaveCount(0);
  });

  test("a trial that has its agent is told it can't hire another", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, agent_limit: 1, agent_limit_reached: true, trial_agent_limit: 1, trial_agent_limit_reached: true },
    });
    // Capacity is authoritative even if this member cannot see the Agent using it.
    await data.agents.interceptGetAgentsRequest({ body: { page: 1, page_size: 50, total: 0, items: [] } });
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await new DashboardPage(page).openHireChoices();

    await expect(page.getByText("Your trial includes 1 agent, and you're using it.")).toBeVisible();
    await expect(page.getByRole("radio", { name: /Ready-made assistant/ })).toBeDisabled();
    await expect(page.getByRole("radio", { name: /Build your own/ })).toBeDisabled();
    await expect(page.getByLabel("Agent name")).toHaveCount(0);
    await expect(page.getByText("Stopping an agent doesn't free a slot.", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "View your agents" }).click();
    await expect(page.getByRole("heading", { name: "How would you like to start?" })).toHaveCount(0);
  });

  test("deleting a trial warns that it ends the free trial for good", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, agent_limit: 1 },
    });
    await data.organizations.interceptGetMembers();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}/members`);
    await page.getByRole("button", { name: /delete organization/i }).click();

    await expect(page.getByRole("dialog")).toContainText("This also ends your free trial");
  });

  test("a trial user left with no organization is told so, not sent to Platform View", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...trialUserContext, organization_users: [] } });
    await data.users.interceptGetOrganizationsRequest();
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false, organization_id: null }));

    await page.goto("/dashboard");

    await expect(page.getByRole("heading", { name: "You're not in an organization" })).toBeVisible();
    await expect(page.getByText(/its organization was deleted/)).toBeVisible();
    await expect(page.getByText("Platform admin access required")).toHaveCount(0);
  });

  for (const entry of ["/dashboard", "/no-organization"]) {
    test(`a backfilled existing user opens their organization from ${entry} without creating one`, async ({ page }) => {
      const data = new DataSupport(page);
      await data.auth.interceptRefreshRequest();
      const account = { ...trialUserContext, signed_up_at: null, organization_users: trialUserContext.organization_users.map((membership) => ({
        ...membership, organization: { ...membership.organization, is_trial: false },
      })) };
      await data.users.interceptGetUserContextRequest({ userContext: account });
      await data.agents.interceptGetAgentsRequest();
      await data.agents.interceptGetAgentHealthRequest();
      const writes: string[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname.startsWith("/api/v1/organizations")) writes.push(request.url());
      });
      await page.goto(entry);
      await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}`);
      await expect(page.getByRole("heading", { name: /your team/i })).toBeVisible();
      await expect(page.getByRole("heading", { name: "You're not in an organization" })).toHaveCount(0);
      expect(writes).toHaveLength(0);
    });
  }
});

test.describe("Gmail in onboarding", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const ADDRESS = "jane@gmail.com";
  const APP_PASSWORD = "abcd efgh ijkl mnop";

  /** Records, in order, each call the Gmail step makes to the trial Agent. */
  async function gmailStepCalls(page: Page, {
    validation = { validation_status: "valid", validation_identity: ADDRESS },
    startStatuses = [200],
  }: { validation?: Record<string, unknown>; startStatuses?: number[] } = {}) {
    const calls: { call: string; body?: unknown }[] = [];
    const agentUrl = `**/api/v1/organizations/*/agents/${TRIAL_AGENT_ID}`;
    await page.route(agentUrl, async (route) => {
      const method = route.request().method();
      if (method === "GET") return route.fulfill({ json: { ...mockAgent, id: TRIAL_AGENT_ID, status: "RUNNING" } });
      if (method !== "PATCH") return route.fallback();
      calls.push({ call: "update", body: route.request().postDataJSON() });
      return route.fulfill({ json: { ...mockAgent, id: TRIAL_AGENT_ID, status: "STOPPED" } });
    });
    await page.route(`${agentUrl}/stop`, async (route) => {
      calls.push({ call: "stop" });
      await route.fulfill({ json: { ...mockAgent, id: TRIAL_AGENT_ID, status: "STOPPED" } });
    });
    await page.route(`${agentUrl}/integrations/gmail_app_password/validate`, async (route) => {
      calls.push({ call: "validate" });
      await route.fulfill({ json: validation });
    });
    let starts = 0;
    await page.route(`${agentUrl}/start`, async (route) => {
      calls.push({ call: "start" });
      const status = startStatuses[Math.min(starts++, startStatuses.length - 1)];
      await route.fulfill(status >= 400
        ? { status, json: { detail: "Unable to start agent" } }
        : { json: { ...mockAgent, id: TRIAL_AGENT_ID, status: "RUNNING" } });
    });
    return calls;
  }

  async function reachGmailStep(page: Page, { skipTelegram = false } = {}) {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts(skipTelegram ? [] : [linkedAccount]);
    await data.onboarding.interceptLinkTokens();
    const completions = await data.onboarding.interceptCompleteOnboarding();
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseQuickStart();
    await (skipTelegram ? wizard.skipAction() : wizard.continueAction()).click();
    await expect(wizard.heading("Let your agent read your Gmail")).toBeVisible();
    return { wizard, completions };
  }

  test("skipping Telegram still offers Gmail, then opens web chat", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const { wizard, completions } = await reachGmailStep(page, { skipTelegram: true });

    await wizard.gmailAddress().fill(ADDRESS);
    await wizard.gmailAppPassword().fill(APP_PASSWORD);
    await wizard.connectGmail().click();

    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`);
    expect(calls.map(({ call }) => call)).toEqual(["stop", "update", "validate", "start"]);
    expect(completions).toHaveLength(1);
  });

  test("after skipping Telegram, I'll do this later still opens web chat", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const { wizard, completions } = await reachGmailStep(page, { skipTelegram: true });

    await wizard.laterAction().click();

    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`);
    expect(calls).toEqual([]);
    expect(completions).toHaveLength(1);
  });

  test("is optional, read-only, and skipping it saves nothing", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const { wizard, completions } = await reachGmailStep(page);

    await expect(page.getByText(/read your inbox, but never send, delete or change mail/)).toBeVisible();
    await expect(page.getByText("myaccount.google.com/apppasswords", { exact: false })).toBeVisible();
    await expect(wizard.connectGmail()).toBeDisabled();
    await wizard.skipGmail().click();

    await expect(wizard.heading("Your agent is live in Telegram.")).toBeVisible();
    expect(completions).toHaveLength(1);
    expect(calls).toEqual([]);
  });

  test("I'll do this later opens the dashboard without saving Gmail", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const { wizard, completions } = await reachGmailStep(page);

    await wizard.laterAction().click();

    await expect(page).toHaveURL(`/dashboard/${TRIAL_ORG_ID}`);
    expect(completions).toHaveLength(1);
    expect(calls).toEqual([]);
  });

  test("connects Gmail, checks the sign-in, and restarts the agent", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const { wizard, completions } = await reachGmailStep(page);

    await wizard.gmailAddress().fill(ADDRESS);
    await wizard.gmailAppPassword().fill(APP_PASSWORD);
    await wizard.connectGmail().click();

    await expect(wizard.heading("Your agent is live in Telegram.")).toBeVisible();
    expect(calls).toEqual([
      { call: "stop" },
      { call: "update", body: { secrets: [{ provider: "gmail_app_password", content: { email: ADDRESS, app_password: APP_PASSWORD } }] } },
      { call: "validate" },
      { call: "start" },
    ]);
    expect(completions).toHaveLength(1);
  });

  test("a rejected app password is removed again and explained", async ({ page }) => {
    const rejected = "Gmail rejected this address and app password. Check both, or create a new app password.";
    const calls = await gmailStepCalls(page, { validation: { validation_status: "invalid", validation_error: rejected } });
    const { wizard, completions } = await reachGmailStep(page);

    await wizard.gmailAddress().fill(ADDRESS);
    await wizard.gmailAppPassword().fill("wrong password");
    await wizard.connectGmail().click();

    await expect(wizard.alert()).toHaveText(rejected);
    await expect(wizard.heading("Let your agent read your Gmail")).toBeVisible();
    expect(calls.map(({ call }) => call)).toEqual(["stop", "update", "validate", "update", "start"]);
    expect(calls[3].body).toEqual({ removed_secret_providers: ["gmail_app_password"] });
    expect(completions).toHaveLength(0);
  });

  test("a failed restart can be tried again", async ({ page }) => {
    const calls = await gmailStepCalls(page, { startStatuses: [500, 200] });
    const { wizard, completions } = await reachGmailStep(page);

    await wizard.gmailAddress().fill(ADDRESS);
    await wizard.gmailAppPassword().fill(APP_PASSWORD);
    await wizard.connectGmail().click();

    await expect(wizard.alert()).toContainText("couldn't restart your agent");
    expect(completions).toHaveLength(0);
    await wizard.retryAction().click();

    await expect(wizard.heading("Your agent is live in Telegram.")).toBeVisible();
    expect(calls.map(({ call }) => call)).toEqual(["stop", "update", "validate", "start", "start"]);
    expect(completions).toHaveLength(1);
  });

  test("a custom agent can connect Gmail right after it is hired", async ({ page }) => {
    const calls = await gmailStepCalls(page);
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    await data.onboarding.interceptCompleteOnboarding([204], { required: false, completed_at: "2026-10-14T12:00:00Z" });
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.agents.interceptCreateAgentRequest({ body: { ...mockAgent, id: TRIAL_AGENT_ID, name: "My helper", status: "STOPPED" } });
    const wizard = new OnboardingPage(page);
    await wizard.goto();
    await wizard.chooseOwnAgent();
    await wizard.agentName().fill("My helper");
    await wizard.template().click();
    await wizard.hireAction().click();

    await expect(wizard.heading("Let your agent read your Gmail")).toBeVisible();
    await expect(wizard.stepCounter()).toHaveText("Step 4 of 5");
    await wizard.gmailAddress().fill(ADDRESS);
    await wizard.gmailAppPassword().fill(APP_PASSWORD);
    await wizard.connectGmail().click();

    await expect(wizard.heading("My helper is ready")).toBeVisible();
    // Hiring started the Agent once; the Gmail step stops it, saves, checks and starts it again.
    expect(calls.map(({ call }) => call)).toEqual(["start", "stop", "update", "validate", "start"]);
  });
});
