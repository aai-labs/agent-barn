import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  OnboardingDataSupport,
  TRIAL_AGENT_ID,
  TRIAL_ORG_ID,
  agentReady,
  onboarding,
  trialUserContext,
} from "../pages/data-support/onboarding-data-support.po";
import { OnboardingPage } from "../pages/onboarding-page.po";
import { org } from "../pages/data-support/organization-data-support.po";

const FREE = { id: "00000000-0000-7000-8000-0000000071e0", key: "free", name: "Free", activation: "free" };
const CLOUD_1 = { id: "00000000-0000-7000-8000-0000000071e1", key: "cloud_1", name: "Cloud Tier 1", activation: "paid" };

function offered(key: string, name: string, activation: string, price: string, features: string[]) {
  return {
    key,
    name,
    tagline: null,
    activation,
    price_usd: price,
    price_note: activation === "paid" ? "per month" : null,
    monthly_usage_usd: activation === "paid" ? price : "0.00",
    one_time_credit_usd: "10.00",
    agent_limit: 1,
    allowed_platform_keys: null,
    features,
    contact_url: activation === "contact" ? "https://agentbarn.dev/pricing" : null,
  };
}

const OFFERED = [
  offered("free", "Free", "free", "0.00", ["team"]),
  offered("cloud_1", "Cloud Tier 1", "paid", "20.00", ["custom_agents", "integrations", "team"]),
  offered("pilot", "Supervised Pilot", "contact", "500.00", ["custom_agents"]),
];

function subscription(overrides: Record<string, unknown> = {}) {
  return {
    id: "aaaaaaaa-0000-4000-8000-0000000000aa",
    tier: CLOUD_1,
    status: "active",
    provider: "mock",
    current_period_start: "2026-11-08T00:00:00Z",
    current_period_end: "2026-12-08T00:00:00Z",
    cancel_at_period_end: false,
    allowance_usd: 20,
    allowance_remaining_usd: 20,
    ...overrides,
  };
}

function holdPreview(overrides: Record<string, unknown> = {}) {
  const item = (id: string, agentName: string, name: string, platformKey: string | null = null) => ({
    id,
    agent_id: "aaaaaaaa-0000-4000-8000-000000000001",
    agent_name: agentName,
    name,
    platform_key: platformKey,
    revision: null,
    suspended_at: null,
  });
  return {
    tier: "Free",
    agents: [
      { id: "aaaaaaaa-0000-4000-8000-000000000002", name: "Support Desk", status: "RUNNING", suspended_at: null },
      { id: "aaaaaaaa-0000-4000-8000-000000000003", name: "Ops Reporter", status: "STOPPED", suspended_at: null },
    ],
    connections: [item("bbbbbbbb-0000-4000-8000-000000000001", "Sales Assistant", "Northwind Slack", "slack")],
    webhooks: [item("bbbbbbbb-0000-4000-8000-000000000002", "Sales Assistant", "Deal won")],
    memory: [item("aaaaaaaa-0000-4000-8000-000000000001", "Sales Assistant", "Sales Assistant")],
    ...overrides,
  };
}

function billing(overrides: Record<string, unknown> = {}) {
  return {
    available: false,
    on_credit: true,
    credit_usd: 10,
    spend_usd: 0,
    balance_usd: 10,
    min_purchase_usd: 5,
    max_purchase_usd: 500,
    purchase_fee_percent: 0,
    upgrade_required: true,
    tier: FREE,
    subscriptions_available: true,
    subscription_provider: "mock",
    tier_assigned_by_platform: false,
    subscription: null,
    history: [],
    ...overrides,
  };
}

async function ownerSignedIn(page: Page) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: UserContext });
  await data.users.interceptGetOrganizationsRequest();
  await data.organizations.interceptGetOrganization({ organization: org({ tier: FREE }) });
  await data.agents.interceptGetAgentsRequest();
  await page.route("**/api/v1/tiers", (route) => route.fulfill({ json: OFFERED }));
  return data;
}

test.describe("Billing · subscribing to a tier", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("an owner on Free subscribes to a paid tier with a demo payment", async ({ page }) => {
    await ownerSignedIn(page);
    let current = billing();
    const subscribed: unknown[] = [];
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/organizations/*/subscription`, (route) => {
      subscribed.push(route.request().postDataJSON());
      current = billing({ tier: CLOUD_1, upgrade_required: false, subscription: subscription() });
      return route.fulfill({ json: { outcome: "active", redirect_url: null, subscription: subscription() } });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);

    const panel = page.getByRole("region", { name: "Tier" });
    await expect(panel).toContainText("Subscribe to a paid tier for monthly usage");
    await expect(page.getByRole("button", { name: "Buy credit" })).toHaveCount(0);
    await expect(panel.getByText("Demo payments: subscribing here charges nothing.")).toBeVisible();
    await panel.getByRole("button", { name: "Subscribe to Cloud Tier 1" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Subscribe" }).click();

    await expect.poll(() => subscribed).toEqual([{ tier_key: "cloud_1" }]);
    await expect(panel).toContainText("Renews on");
    await expect(panel.getByRole("button", { name: "Cancel subscription" })).toBeVisible();
    await expect(panel.getByRole("listitem", { name: "Supervised Pilot" }).getByRole("link", { name: "Book a call" })).toHaveAttribute(
      "href",
      "https://agentbarn.dev/pricing",
    );
  });

  test("subscribing ends the trial, so its owner can create organizations without reloading", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization({
      organization: { ...trialUserContext.organization_users[0].organization, tier: FREE },
    });
    await data.agents.interceptGetAgentsRequest();
    await page.route("**/api/v1/tiers", (route) => route.fulfill({ json: OFFERED }));
    const ended = { ...structuredClone(trialUserContext), trial_ended_at: "2026-11-09T09:00:00Z" };
    ended.organization_users[0].organization.is_trial = false;
    let user: unknown = trialUserContext;
    await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: user }));
    let current = billing();
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/organizations/*/subscription`, (route) => {
      user = ended;
      current = billing({ tier: CLOUD_1, upgrade_required: false, subscription: subscription() });
      return route.fulfill({ json: { outcome: "active", redirect_url: null, subscription: subscription() } });
    });

    await page.goto(`/dashboard/${TRIAL_ORG_ID}/billing`);
    const switcher = page.getByRole("button", { name: /Jane's Organization/ }).first();
    await switcher.click();
    await expect(page.getByRole("menuitem", { name: "Create organization" })).toHaveCount(0);
    await page.keyboard.press("Escape");

    const panel = page.getByRole("region", { name: "Tier" });
    await panel.getByRole("button", { name: "Subscribe to Cloud Tier 1" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Subscribe" }).click();
    await expect(panel).toContainText("Renews on");

    await switcher.click();
    await expect(page.getByRole("menuitem", { name: "Create organization" })).toBeVisible();
  });

  test("cancelling says what Free won't cover before it is confirmed", async ({ page }) => {
    await ownerSignedIn(page);
    let current = billing({ tier: CLOUD_1, upgrade_required: false, subscription: subscription() });
    const previewed: string[] = [];
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/organizations/*/subscription/preview*`, (route) => {
      previewed.push(new URL(route.request().url()).searchParams.get("tier_key") ?? "");
      return route.fulfill({ json: holdPreview() });
    });
    await page.route(`**/api/v1/organizations/*/subscription/cancel`, (route) => {
      const cancelled = subscription({ cancel_at_period_end: true });
      current = billing({ tier: CLOUD_1, upgrade_required: false, subscription: cancelled });
      return route.fulfill({ json: cancelled });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    const panel = page.getByRole("region", { name: "Tier" });
    await panel.getByRole("button", { name: "Cancel subscription" }).click();

    const dialog = page.getByRole("dialog", { name: "Cancel your subscription?" });
    const held = dialog.getByLabel("What goes on hold");
    await expect(held).toContainText("2 agents: Support Desk, Ops Reporter");
    await expect(held).toContainText("1 channel: Northwind Slack (Slack)");
    await expect(held).toContainText("1 webhook: Deal won");
    await expect(held).toContainText("Long-term memory on Sales Assistant");
    await expect(held).toContainText("You can choose different ones afterwards in Settings, Tier.");
    expect(previewed).toEqual(["free"]);
    await dialog.getByRole("button", { name: "Cancel subscription" }).click();

    await expect(panel).toContainText("then your organization moves to Free and keeps its credit");
    await expect(panel.getByRole("button", { name: "Keep subscription" })).toBeVisible();
  });

  test("switching to a smaller tier says what it won't cover", async ({ page }) => {
    await ownerSignedIn(page);
    const cloud2 = { id: "00000000-0000-7000-8000-0000000071e2", key: "cloud_2", name: "Cloud Tier 2", activation: "paid" };
    await page.route("**/api/v1/tiers", (route) =>
      route.fulfill({ json: [...OFFERED, offered("cloud_2", "Cloud Tier 2", "paid", "100.00", ["custom_agents"])] }),
    );
    await page.route(`**/api/v1/organizations/*/billing`, (route) =>
      route.fulfill({ json: billing({ tier: cloud2, upgrade_required: false, subscription: subscription({ tier: cloud2 }) }) }),
    );
    await page.route(`**/api/v1/organizations/*/subscription/preview*`, (route) =>
      route.fulfill({ json: holdPreview({ tier: "Cloud Tier 1", connections: [], webhooks: [], memory: [] }) }),
    );

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    await page.getByRole("button", { name: "Switch to Cloud Tier 1" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("What goes on hold")).toContainText("Cloud Tier 1 doesn't cover everything");
    await expect(dialog.getByLabel("What goes on hold")).toContainText("2 agents: Support Desk, Ops Reporter");
  });
});

test.describe("Billing · paying through Stripe", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const stripeSubscription = (overrides: Record<string, unknown> = {}) =>
    subscription({ provider: "stripe", manageable: true, ...overrides });

  test("subscribing goes to Stripe's page, and coming back says when it has started", async ({ page }) => {
    await ownerSignedIn(page);
    let current = billing({ subscription_provider: "stripe" });
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/organizations/*/subscription`, (route) =>
      route.fulfill({ json: { outcome: "redirect", redirect_url: "https://checkout.stripe.test/c", subscription: null } }),
    );
    await page.route("https://checkout.stripe.test/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<h1>Stripe Checkout</h1>" }),
    );

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    await expect(page.getByText("Demo payments")).toHaveCount(0);
    await page.getByRole("button", { name: "Subscribe to Cloud Tier 1" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("You'll pay on Stripe's secure page.");
    await dialog.getByRole("button", { name: "Continue to payment" }).click();
    await expect(page.getByRole("heading", { name: "Stripe Checkout" })).toBeVisible();

    current = billing({ subscription_provider: "stripe", tier: CLOUD_1, upgrade_required: false, subscription: stripeSubscription() });
    await page.goto(`/dashboard/${TEST_ORG_ID}/billing?subscription=started`);
    await expect(page.getByText("You're subscribed to Cloud Tier 1.")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/dashboard/${TEST_ORG_ID}/billing$`));
  });

  test("an upgrade is charged now and a downgrade waits for the renewal", async ({ page }) => {
    await ownerSignedIn(page);
    const cloud2 = { id: "00000000-0000-7000-8000-0000000071e2", key: "cloud_2", name: "Cloud Tier 2", activation: "paid" };
    await page.route("**/api/v1/tiers", (route) =>
      route.fulfill({ json: [...OFFERED, offered("cloud_2", "Cloud Tier 2", "paid", "100.00", ["custom_agents"])] }),
    );
    await page.route(`**/api/v1/organizations/*/subscription/preview*`, (route) =>
      route.fulfill({ json: holdPreview({ agents: [], connections: [], webhooks: [], memory: [] }) }),
    );
    let current = billing({ subscription_provider: "stripe", tier: CLOUD_1, upgrade_required: false, subscription: stripeSubscription() });
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    await page.getByRole("button", { name: "Switch to Cloud Tier 2" }).click();
    await expect(page.getByRole("dialog")).toContainText("It applies straight away, and you're charged for the rest of this month now.");
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

    current = billing({ subscription_provider: "stripe", tier: cloud2, upgrade_required: false, subscription: stripeSubscription({ tier: cloud2 }) });
    await page.reload();
    await page.getByRole("button", { name: "Switch to Cloud Tier 1" }).click();
    await expect(page.getByRole("dialog")).toContainText("You keep Cloud Tier 2 until Dec 8, 2026, then move to Cloud Tier 1.");
  });

  test("a scheduled downgrade can be taken back", async ({ page }) => {
    await ownerSignedIn(page);
    const cloud2 = { id: "00000000-0000-7000-8000-0000000071e2", key: "cloud_2", name: "Cloud Tier 2", activation: "paid" };
    await page.route(`**/api/v1/organizations/*/billing`, (route) =>
      route.fulfill({
        json: billing({
          subscription_provider: "stripe",
          tier: cloud2,
          upgrade_required: false,
          subscription: stripeSubscription({ tier: cloud2, scheduled_tier: CLOUD_1 }),
        }),
      }),
    );
    const posted: unknown[] = [];
    await page.route(`**/api/v1/organizations/*/subscription`, (route) => {
      posted.push(route.request().postDataJSON());
      return route.fulfill({ json: { outcome: "active", redirect_url: null, subscription: stripeSubscription({ tier: cloud2 }) } });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    const panel = page.getByRole("region", { name: "Tier" });
    await expect(panel).toContainText("Moves to Cloud Tier 1 on Dec 8, 2026. Until then you keep Cloud Tier 2.");
    await panel.getByRole("button", { name: "Keep Cloud Tier 2" }).click();

    await expect.poll(() => posted).toEqual([{ tier_key: "cloud_2" }]);
  });

  test("a failed payment says by when to fix it, and the card is updated on Stripe's page", async ({ page }) => {
    await ownerSignedIn(page);
    await page.route(`**/api/v1/organizations/*/billing`, (route) =>
      route.fulfill({
        json: billing({
          subscription_provider: "stripe",
          tier: CLOUD_1,
          upgrade_required: false,
          subscription: stripeSubscription({
            status: "past_due",
            past_due_since: "2026-11-09T00:00:00Z",
            grace_ends_at: "2026-11-16T00:00:00Z",
          }),
        }),
      }),
    );
    await page.route(`**/api/v1/organizations/*/subscription/portal`, (route) =>
      route.fulfill({ json: { url: "https://billing.stripe.test/session" } }),
    );
    await page.route("https://billing.stripe.test/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<h1>Stripe billing</h1>" }),
    );

    await page.goto(`/dashboard/${TEST_ORG_ID}/billing`);
    const panel = page.getByRole("region", { name: "Tier" });
    await expect(panel.getByRole("alert")).toHaveText("Your last payment failed. Update your card by Nov 16, 2026 to keep Cloud Tier 1.");
    await expect(panel).not.toContainText("Renews on");
    await panel.getByRole("button", { name: "Manage payment" }).click();

    await expect(page.getByRole("heading", { name: "Stripe billing" })).toBeVisible();
  });
});

test.describe("Onboarding · choosing a tier", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the tier step comes first and remembers the tier picked on the pricing page", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization({
      organization: {
        ...trialUserContext.organization_users[0].organization,
        tier: FREE,
        entitlements: { features: ["team"], allowed_platform_keys: ["agentbarn_telegram", "web"] },
      },
    });
    await new OnboardingDataSupport(page).interceptGetOnboarding(onboarding());
    await page.route(`**/api/v1/organizations/${TRIAL_ORG_ID}/billing`, (route) => route.fulfill({ json: billing() }));
    await page.route("**/api/v1/tiers", (route) => route.fulfill({ json: OFFERED }));

    await page.goto("/onboarding?tier=cloud_1");

    await expect(page.getByRole("heading", { name: "Choose your tier" })).toBeVisible();
    await expect(page.getByText("You picked Cloud Tier 1 on our pricing page.")).toBeVisible();
    await page.getByRole("button", { name: "Continue with Free" }).click();
    await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible();
    // Free hires only the ready-made assistant.
    await expect(page.getByRole("radio", { name: /Build my own agent/ })).toHaveCount(0);
  });

  async function paidOwnerOnboarding(page: Page, billingBody: () => unknown) {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization({
      organization: {
        ...trialUserContext.organization_users[0].organization,
        is_trial: false,
        tier: CLOUD_1,
        entitlements: { features: ["custom_agents", "integrations", "team"], allowed_platform_keys: null },
      },
    });
    await new OnboardingDataSupport(page).interceptGetOnboarding(onboarding());
    await page.route(`**/api/v1/organizations/${TRIAL_ORG_ID}/billing`, (route) => route.fulfill({ json: billingBody() }));
    await page.route("**/api/v1/tiers", (route) => route.fulfill({ json: OFFERED }));
    return data;
  }

  const paidBilling = () =>
    billing({
      subscription_provider: "stripe",
      tier: CLOUD_1,
      upgrade_required: false,
      subscription: subscription({ provider: "stripe", manageable: true }),
    });

  test("on a paid tier the ready-made assistant chats on the web, without the Telegram bot", async ({ page }) => {
    await paidOwnerOnboarding(page, paidBilling);
    const support = new OnboardingDataSupport(page);
    await support.interceptSetUpAgent([onboarding({ ...agentReady, connection_id: null })]);
    await support.interceptCompleteOnboarding();
    const wizard = new OnboardingPage(page);

    await wizard.goto();

    await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible();
    await expect(page.getByText("Chat with it on the web straight away.")).toBeVisible();
    await expect(page.getByText("Connect Telegram")).toHaveCount(0);
    await expect(page.getByText("Free trial")).toHaveCount(0);
    await expect(page.getByText("Cloud Tier 1", { exact: true })).toBeVisible();
    await wizard.chooseQuickStart();
    await expect(page.getByRole("heading", { name: "Let your agent read your Gmail" })).toBeVisible();
    await wizard.skipGmail().click();
    await page.waitForURL(`/dashboard/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}?tab=chat`);
  });

  test("coming back from Stripe waits for the subscription, then goes on without the tier step", async ({ page }) => {
    let paidFor = false;
    await paidOwnerOnboarding(page, () =>
      paidFor ? paidBilling() : billing({ subscription_provider: "stripe" }),
    );

    await page.goto("/onboarding?subscription=started");

    await expect(page.getByRole("heading", { name: "Confirming your payment" })).toBeVisible();
    await expect(page).toHaveURL(/\/onboarding$/);
    paidFor = true;
    await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("heading", { name: "Choose your tier" })).toHaveCount(0);
  });

  test("the sign-up page carries the tier to Google", async ({ page }) => {
    await page.goto("/signup?tier=cloud_1");

    await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveAttribute(
      "href",
      "/api/v1/auth/google/start?origin=signup&tier=cloud_1",
    );
  });
});
