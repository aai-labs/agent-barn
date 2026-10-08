import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  agentReady,
  onboarding,
  TRIAL_DEEP_LINK,
  TRIAL_FRESH_DEEP_LINK,
  TRIAL_ORG_ID,
  trialUserContext,
} from "../pages/data-support/onboarding-data-support.po";
import { OnboardingPage } from "../pages/onboarding-page.po";

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
  return data;
}

test.describe("Trial sign-in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    await new DataSupport(page).auth.interceptLogoutRequest();
  });

  test("signing up starts with Google, as step 1 of 3", async ({ page }) => {
    const onboardingPage = new OnboardingPage(page);
    await onboardingPage.gotoSignup();

    await expect(onboardingPage.heading("Sign in to Agent Barn")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 1 of 3");
    await expect(page.getByText("New here? Signing in creates your account.")).toBeVisible();
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
    await expect(page.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup");
  });
});

test.describe("Trial onboarding", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("sets up the agent, links Telegram, and finishes", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding();
    const setUps = await data.onboarding.interceptSetUpAgent();
    const linked = await data.onboarding.interceptLinkedAccounts();
    await data.onboarding.interceptLinkTokens({ statuses: ["waiting", "waiting", "linked"] });
    const completions = await data.onboarding.interceptCompleteOnboarding();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();

    await expect(onboardingPage.heading("Say hi to @AgentBarnTestBot.")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 2 of 3");
    await expect(onboardingPage.openInTelegram()).toHaveAttribute("href", TRIAL_DEEP_LINK);
    await expect(onboardingPage.openInTelegram()).toHaveAttribute("target", "_blank");
    expect(setUps).toHaveLength(1);

    linked.set([linkedAccount]);
    await onboardingPage.openInTelegram().click();
    await expect(page.getByText("Linked as @jane_doe")).toBeVisible();

    await onboardingPage.continueAction().click();

    await expect(onboardingPage.heading("Your agent is live in Telegram.")).toBeVisible();
    await expect(onboardingPage.stepCounter()).toHaveText("Step 3 of 3");
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
    await onboardingPage.openInTelegram().click();

    await expect(onboardingPage.alert()).toHaveText(/That link expired after 10 minutes\. Here.s a fresh one\./);
    await expect(page.getByRole("link", { name: "Open in Telegram again" })).toHaveAttribute(
      "href",
      TRIAL_FRESH_DEEP_LINK,
    );
  });

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

    await expect(onboardingPage.alert()).toHaveText(/We couldn.t start your agent/);
    await onboardingPage.retryAction().click();

    await expect(onboardingPage.openInTelegram()).toBeVisible();
    expect(setUps).toHaveLength(2);
  });

  test("someone already linked goes straight to Continue", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding(agentReady));
    await data.onboarding.interceptSetUpAgent();
    await data.onboarding.interceptLinkedAccounts([linkedAccount]);
    await data.onboarding.interceptLinkTokens();
    const onboardingPage = new OnboardingPage(page);

    await onboardingPage.goto();

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
    await onboardingPage.continueAction().click();
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
      organization: { ...trialUserContext.organization_users[0].organization, trial_agent_limit: 50 },
    });
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: "Hire agent" }).click();

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

    await expect(page.getByRole("button", { name: "Create organization" })).toBeVisible();
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

    await expect(page.getByRole("button", { name: "Create organization" })).toHaveCount(0);
  });

  test("a trial user can't create another organization", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: /Jane's Organization/ }).first().click();

    await expect(page.getByRole("button", { name: "Create organization" })).toHaveCount(0);
  });

  test("a trial that has its agent is told it can't hire another", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, trial_agent_limit: 1 },
    });
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();

    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await page.getByRole("button", { name: "Hire agent" }).click();

    await expect(page.getByText("Trial organizations can have 1 agent.")).toBeVisible();
    await expect(page.getByLabel("Agent name")).toHaveCount(0);
  });

  test("deleting a trial warns that it ends the free trial for good", async ({ page }) => {
    const data = await signedInTrialUser(page);
    await data.onboarding.interceptGetOnboarding(onboarding({ required: false }));
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, trial_agent_limit: 1 },
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
    await expect(page.getByText(/free trial has ended/)).toBeVisible();
    await expect(page.getByText("Platform admin access required")).toHaveCount(0);
  });

  test("an invited user left with no organization is asked to get an invitation", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: { ...trialUserContext, signed_up_at: null, organization_users: [] },
    });
    await data.users.interceptGetOrganizationsRequest();

    await page.goto("/dashboard");

    await expect(page.getByRole("heading", { name: "You're not in an organization" })).toBeVisible();
    await expect(page.getByText(/Ask someone to invite you/)).toBeVisible();
  });
});
