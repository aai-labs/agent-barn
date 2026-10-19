import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import { organizationLlmBudget } from "../pages/data-support/organization-data-support.po";

const BILLING_URL = `/dashboard/${TEST_ORG_ID}/billing`;
const CHECKOUT_URL = "https://checkout.stripe.test/cs_test";

function billing(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    on_credit: true,
    credit_usd: 10,
    spend_usd: 2.5,
    balance_usd: 7.5,
    min_purchase_usd: 5,
    max_purchase_usd: 500,
    purchase_fee_percent: 0,
    history: [{ kind: "trial", credit_usd: 10, amount_paid_usd: null, created_at: "2026-10-01T09:00:00Z" }],
    ...overrides,
  };
}

async function signedIn(page: Page, { role = "OWNER", platformAdmin = false } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({
    userContext: {
      ...UserContext,
      is_platform_admin: platformAdmin,
      organization_users: UserContext.organization_users.map((membership) => ({ ...membership, role })),
    },
  });
  await data.users.interceptGetOrganizationsRequest();
  await data.organizations.interceptGetOrganization();
  await data.agents.interceptGetAgentsRequest();
  await data.agents.interceptGetAgentHealthRequest();
  return data;
}

async function interceptBilling(page: Page, body: Record<string, unknown>) {
  const checkouts: unknown[] = [];
  await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: body }));
  await page.route(`**/api/v1/organizations/*/billing/checkout`, (route) => {
    checkouts.push(route.request().postDataJSON());
    return route.fulfill({ json: { url: CHECKOUT_URL } });
  });
  await page.route("https://checkout.stripe.test/**", (route) =>
    route.fulfill({ contentType: "text/html", body: "<html><body>Stripe Checkout</body></html>" }),
  );
  return checkouts;
}

test.describe("Billing", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the owner sees their credit, balance and history", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(BILLING_URL);

    await expect(page.getByRole("heading", { name: "Billing", exact: true })).toBeVisible();
    const balance = page.getByRole("region", { name: "Balance" });
    await expect(balance).toContainText("$7.50");
    await expect(balance).toContainText("$2.50 of $10.00 used");
    await expect(page.getByRole("table")).toContainText("Trial credit");
  });

  test("the history says who bought each purchase", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(
      page,
      billing({
        history: [
          {
            kind: "purchase",
            credit_usd: 20,
            amount_paid_usd: 20,
            purchased_by: "Jane Owner",
            created_at: "2026-10-02T09:00:00Z",
          },
          { kind: "trial", credit_usd: 10, amount_paid_usd: null, purchased_by: null, created_at: "2026-10-01T09:00:00Z" },
        ],
      }),
    );
    await page.goto(BILLING_URL);

    const rows = page.getByRole("table").getByRole("row");
    await expect(rows.filter({ hasText: "Purchase" })).toContainText("Jane Owner");
    await expect(rows.filter({ hasText: "Trial credit" })).not.toContainText("Jane Owner");
  });

  test("the owner buys credit and is sent to pay for it", async ({ page }) => {
    await signedIn(page);
    const checkouts = await interceptBilling(page, billing({ purchase_fee_percent: 5.5 }));
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("20");
    await expect(dialog).toContainText("You'll pay $21.10");
    await dialog.getByRole("button", { name: "Continue to payment" }).click();

    await page.waitForURL(CHECKOUT_URL);
    expect(checkouts).toEqual([{ credit_usd: 20 }]);
  });

  test("an amount outside the platform's bounds is refused before any request", async ({ page }) => {
    await signedIn(page);
    const checkouts = await interceptBilling(page, billing());
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("4");

    await expect(dialog.getByText("Choose between $5.00 and $500.00.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    expect(checkouts).toEqual([]);
  });

  test("an amount in dollars and cents is accepted", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("5.10");

    await expect(dialog).toContainText("You'll pay $5.10");
    await expect(dialog.getByRole("button", { name: "Continue to payment" })).toBeEnabled();
  });

  for (const typed of ["20.005", "1e1", "0x10"]) {
    test(`"${typed}" is asked for again as dollars and cents`, async ({ page }) => {
      await signedIn(page);
      await interceptBilling(page, billing());
      await page.goto(BILLING_URL);

      await page.getByRole("button", { name: "Buy credit" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Credit to add").fill(typed);

      await expect(dialog.getByText("Enter an amount in dollars and cents, like 20 or 20.50.")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    });
  }

  test("a payment the server can't start says why, in the dialog", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.route(`**/api/v1/organizations/*/billing/checkout`, (route) =>
      route.fulfill({ status: 503, json: { detail: "Payments aren't available right now. Try again shortly." } }),
    );
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("20");
    await dialog.getByRole("button", { name: "Continue to payment" }).click();

    await expect(dialog.getByRole("alert")).toContainText("Try again shortly");
    await expect(page).toHaveURL(new RegExp(`${BILLING_URL}$`));
  });

  test("coming back from a payment says the credit is on its way", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`${BILLING_URL}?checkout=success`);

    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toBeVisible();
  });

  test("credit that arrives after paying shows without a reload, and the page says it arrived", async ({ page }) => {
    await signedIn(page);
    let current = billing();
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.goto(`${BILLING_URL}?checkout=success`);
    const balance = page.getByRole("region", { name: "Balance" });
    await expect(balance).toContainText("$7.50");

    current = billing({ credit_usd: 30, balance_usd: 27.5 });

    await expect(balance).toContainText("$27.50", { timeout: 15000 });
    await expect(page.getByRole("status").filter({ hasText: "Your credit has been added." })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toHaveCount(0);
  });

  test("credit that arrived before the owner got back is said to have arrived", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    let current = billing();
    // Registered last, so it answers billing reads ahead of the fixed one above.
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    await page.goto(BILLING_URL);
    await page.getByRole("button", { name: "Buy credit" }).click();
    await page.getByRole("dialog").getByLabel("Credit to add").fill("20");
    await page.getByRole("dialog").getByRole("button", { name: "Continue to payment" }).click();
    await page.waitForURL(CHECKOUT_URL);

    // Stripe's webhook usually lands before the owner is sent back.
    current = billing({ credit_usd: 30, balance_usd: 27.5 });
    await page.goto(`${BILLING_URL}?checkout=success`);

    await expect(page.getByRole("status").filter({ hasText: "Your credit has been added." })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toHaveCount(0);
  });

  test("the payment message doesn't come back on a reload", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`${BILLING_URL}?checkout=success`);
    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${BILLING_URL}$`));

    await page.reload();

    await expect(page.getByRole("region", { name: "Balance" })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toHaveCount(0);
  });

  test("a payment still processing after a minute says so", async ({ page }) => {
    await page.clock.install();
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`${BILLING_URL}?checkout=success`);
    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toBeVisible();

    await page.clock.fastForward(61_000);

    await expect(page.getByRole("status").filter({ hasText: "still being processed" })).toBeVisible();
  });

  test("a cancelled payment says nothing was charged", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`${BILLING_URL}?checkout=cancelled`);

    await expect(page.getByRole("status").filter({ hasText: "Nothing was charged" })).toBeVisible();
  });

  test("a balance that can't be read yet isn't shown as used up", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ spend_usd: null, balance_usd: null }));
    await page.goto(BILLING_URL);

    const balance = page.getByRole("region", { name: "Balance" });
    await expect(balance.getByText("Not available yet").first()).toBeVisible();
    await expect(balance.getByText("Used up")).toHaveCount(0);
  });

  test("a used-up balance says so", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ spend_usd: 10.2, balance_usd: -0.2 }));
    await page.goto(BILLING_URL);

    await expect(page.getByRole("region", { name: "Balance" }).getByText("Used up")).toBeVisible();
  });

  test("an organization without credit history says so", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ history: [] }));
    await page.goto(BILLING_URL);

    await expect(page.getByText("No credit added yet.")).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
  });

  test("an organization whose plan covers its spend shows no balance", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ available: false, on_credit: false, balance_usd: -40 }));
    await page.goto(BILLING_URL);

    await expect(page.getByText("This organization's spend is covered by its plan, so it doesn't buy credit.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Balance" })).toHaveCount(0);
  });

  test("someone without access to billing is told so, with nothing to retry", async ({ page }) => {
    await signedIn(page, { role: "ADMIN" });
    await page.route(`**/api/v1/organizations/*/billing`, (route) =>
      route.fulfill({ status: 403, json: { detail: "You don't have access to this organization's billing." } }),
    );
    await page.goto(BILLING_URL);

    await expect(page.getByText("You don't have access to this organization's billing.")).toBeVisible();
    await expect(page.getByRole("button", { name: /try again/i })).toHaveCount(0);
  });

  test("the owner gets a Billing tab only when credit can be bought", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ available: false }));
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Settings", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Billing", exact: true })).toHaveCount(0);
  });

  test("the owner's Billing tab leads to the page", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Billing", exact: true }).first()).toHaveAttribute("href", BILLING_URL);
  });

  test("an admin who isn't the owner gets no Billing tab", async ({ page }) => {
    await signedIn(page, { role: "ADMIN" });
    await interceptBilling(page, billing());
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Settings", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Billing", exact: true })).toHaveCount(0);
  });

  test("an organization that has used all its credit is told, and its owner can buy more", async ({ page }) => {
    const data = await signedIn(page);
    await interceptBilling(page, billing({ spend_usd: 10.2, balance_usd: -0.2 }));
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({
        state: "exhausted",
        window: "once",
        limit_usd: 10,
        ceiling_usd: 10,
        spend_usd: 10.2,
        renews_at: null,
      }),
    });
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    const banner = page.getByRole("status").filter({ hasText: "used all its credit" });
    await expect(banner).toBeVisible();
    await expect(banner).not.toContainText("renew");
    await expect(banner.getByRole("link", { name: "Buy credit" })).toHaveAttribute("href", BILLING_URL);
  });

  test("the out-of-credit notice goes once bought credit arrives", async ({ page }) => {
    await signedIn(page);
    let current = billing({ spend_usd: 10.2, balance_usd: -0.2 });
    await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: current }));
    let budget = organizationLlmBudget({
      state: "exhausted",
      window: "once",
      limit_usd: 10,
      ceiling_usd: 10,
      spend_usd: 10.2,
      renews_at: null,
    });
    await page.route(`**/api/v1/organizations/${TEST_ORG_ID}/llm-budget`, (route) =>
      route.request().method() === "GET" ? route.fulfill({ json: budget }) : route.fallback(),
    );
    await page.goto(`${BILLING_URL}?checkout=success`);
    await expect(page.getByRole("status").filter({ hasText: "used all its credit" })).toBeVisible();

    current = billing({ credit_usd: 30, spend_usd: 10.2, balance_usd: 19.8 });
    budget = organizationLlmBudget({ state: "ok", window: "once", limit_usd: 30, ceiling_usd: 30, spend_usd: 10.2, renews_at: null });

    await expect(page.getByRole("status").filter({ hasText: "Your credit has been added." })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("status").filter({ hasText: "used all its credit" })).toHaveCount(0);
  });
});

test.describe("Platform · Billing settings", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a Platform Administrator sets the purchase bounds, rate and fee", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformMemory.intercept();
    const saved: unknown[] = [];
    let current = {
      payments_enabled: true,
      payments_configured: true,
      min_purchase_usd: 5,
      max_purchase_usd: 500,
      purchase_fee_percent: 0,
      updated_at: null,
    };
    await page.route("**/api/v1/platform/settings/billing", (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as Record<string, number>;
        saved.push(body);
        current = { ...current, ...body };
      }
      return route.fulfill({ json: current });
    });

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Billing" }).click();
    const section = page.getByRole("region", { name: "Billing" });
    await expect(section).toContainText("$5.00");

    await section.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Smallest purchase").fill("10");
    await page.getByLabel("Purchase fee").fill("5.5");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    const confirm = page.getByRole("dialog");
    await expect(confirm).toContainText("Each $1.00 of credit will cost buyers $1.06.");
    await expect(confirm.getByRole("alert")).toHaveCount(0);
    expect(saved).toHaveLength(0);
    await confirm.getByRole("button", { name: "Save settings" }).click();

    await expect(section.getByRole("status")).toContainText("Billing settings saved.");
    await expect(section).toContainText("$10.00");
    await expect(section).toContainText("5.5%");
    expect(saved).toHaveLength(1);
    // $1 of credit is $1 of model spend: the fee is the only markup.
    expect(saved[0]).not.toHaveProperty("credit_rate");
    await expect(section.getByText("Credit per dollar")).toHaveCount(0);
  });

  for (const [label, typed, message] of [
    ["Smallest purchase", "0.49", "Enter an amount from $0.50 to $100,000.00."],
    ["Largest purchase", "100001", "Enter an amount from the smallest purchase to $100,000.00."],
    ["Purchase fee", "101", "Enter a percentage from 0 to 100."],
  ] as const) {
    test(`${label} refuses ${typed} before saving`, async ({ page }) => {
      const data = new DataSupport(page);
      await data.auth.interceptRefreshRequest();
      await data.users.interceptGetUserContextRequest();
      await data.users.interceptGetOrganizationsRequest();
      await data.platformMemory.intercept();
      await page.route("**/api/v1/platform/settings/billing", (route) =>
        route.fulfill({
          json: {
            payments_enabled: true,
            payments_configured: true,
            min_purchase_usd: 5,
            max_purchase_usd: 500,
            purchase_fee_percent: 0,
            updated_at: null,
          },
        }),
      );
      await page.goto("/dashboard/platform/settings");
      await page.getByRole("button", { name: "Billing" }).click();
      const section = page.getByRole("region", { name: "Billing" });
      await section.getByRole("button", { name: "Edit" }).click();

      await page.getByLabel(label).fill(typed);

      await expect(section.getByText(message)).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });
  }

  async function openSettings(page: Page, initial: Record<string, unknown>) {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformMemory.intercept();
    const saved: Record<string, unknown>[] = [];
    let current = {
      payments_enabled: false,
      payments_configured: true,
      min_purchase_usd: 5,
      max_purchase_usd: 500,
      purchase_fee_percent: 0,
      updated_at: null,
      ...initial,
    };
    await page.route("**/api/v1/platform/settings/billing", (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        saved.push(body);
        current = { ...current, ...body };
      }
      return route.fulfill({ json: current });
    });
    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Billing" }).click();
    return { section: page.getByRole("region", { name: "Billing" }), saved };
  }

  test("payments are off until a Platform Administrator turns them on", async ({ page }) => {
    const { section, saved } = await openSettings(page, {});
    await expect(section.getByText("Organizations can't buy credit until payments are turned on.")).toBeVisible();
    await expect(section.getByTestId("saved-payments")).toHaveText("Off");

    await section.getByRole("button", { name: "Edit" }).click();
    const toggle = section.getByRole("switch", { name: "Take payments" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const confirm = page.getByRole("dialog");
    await expect(confirm).toContainText("Organizations on credit will be able to buy it.");
    await confirm.getByRole("button", { name: "Save settings" }).click();

    await expect(section.getByRole("status")).toContainText("Billing settings saved.");
    await expect(section.getByTestId("saved-payments")).toHaveText("On");
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ payments_enabled: true });
    await expect(section.getByText("Organizations can't buy credit until payments are turned on.")).toHaveCount(0);
  });

  test("turning payments off says new purchases stop", async ({ page }) => {
    const { section } = await openSettings(page, { payments_enabled: true });
    await section.getByRole("button", { name: "Edit" }).click();
    await section.getByRole("switch", { name: "Take payments" }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(page.getByRole("dialog")).toContainText(
      "Organizations will no longer be able to buy credit. Payments already made still arrive.",
    );
  });

  test("payments can't be turned on until this deployment is set up to take them", async ({ page }) => {
    const { section } = await openSettings(page, { payments_configured: false });
    await expect(section.getByText("This deployment isn't set up to take payments yet.")).toBeVisible();

    await section.getByRole("button", { name: "Edit" }).click();

    await expect(section.getByRole("switch", { name: "Take payments" })).toBeDisabled();
  });

  test("payments left on that this deployment can't take are said to be unavailable, and can be turned off", async ({
    page,
  }) => {
    const { section } = await openSettings(page, { payments_enabled: true, payments_configured: false });
    await expect(
      section.getByText("Payments are on, but this deployment can't take them right now, so organizations can't buy credit."),
    ).toBeVisible();

    await section.getByRole("button", { name: "Edit" }).click();

    await expect(section.getByRole("switch", { name: "Take payments" })).toBeEnabled();
  });
});

test.describe("Platform · Billing", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  function record(overrides: Record<string, unknown> = {}) {
    return {
      organization_id: TEST_ORG_ID,
      organization_name: "Acme",
      kind: "purchase",
      credit_usd: 20,
      amount_paid_usd: 21.1,
      by: "Jane Owner",
      reference: "pi_123",
      created_at: "2026-10-02T09:00:00Z",
      ...overrides,
    };
  }

  async function platformAdmin(page: Page, pages: Record<string, unknown>[][]) {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    const requests: URLSearchParams[] = [];
    await page.route("**/api/v1/platform/billing/credit-history**", (route) => {
      const params = new URL(route.request().url()).searchParams;
      requests.push(params);
      const pageNumber = Number(params.get("page") ?? "1");
      const total = pages.reduce((sum, items) => sum + items.length, 0);
      return route.fulfill({
        json: { page: pageNumber, page_size: Math.max(1, pages[0].length), total, items: pages[pageNumber - 1] ?? [] },
      });
    });
    return requests;
  }

  test("a Platform Administrator sees every organization's purchases, refunds and credit", async ({ page }) => {
    await platformAdmin(page, [
      [
        record(),
        record({
          organization_name: "Beta",
          kind: "refund",
          credit_usd: -5,
          amount_paid_usd: null,
          by: "Payment provider",
          reference: "re_9",
        }),
      ],
    ]);
    await page.goto("/dashboard/platform/billing");

    await expect(page.getByRole("heading", { name: "Billing", exact: true })).toBeVisible();
    const rows = page.getByRole("table").getByRole("row");
    await expect(rows.filter({ hasText: "Acme" })).toContainText("Purchase");
    await expect(rows.filter({ hasText: "Acme" })).toContainText("Jane Owner");
    await expect(rows.filter({ hasText: "Acme" })).toContainText("$21.10");
    await expect(rows.filter({ hasText: "Acme" })).toContainText("pi_123");
    await expect(rows.filter({ hasText: "Beta" })).toContainText("−$5.00");
  });

  test("the list narrows to one kind", async ({ page }) => {
    const requests = await platformAdmin(page, [[record()]]);
    await page.goto("/dashboard/platform/billing");
    await expect(page.getByRole("table")).toContainText("Acme");

    await page.getByLabel("Kind").selectOption({ label: "Refunds" });

    await expect.poll(() => requests.at(-1)?.get("kind")).toBe("refund");
  });

  test("an empty list says whether it's the filter that emptied it", async ({ page }) => {
    await platformAdmin(page, [[]]);
    await page.goto("/dashboard/platform/billing");
    await expect(page.getByText("No credit changes yet.")).toBeVisible();

    await page.getByLabel("Kind").selectOption({ label: "Refunds" });

    await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
  });

  test("more is loaded on request", async ({ page }) => {
    await platformAdmin(page, [[record()], [record({ organization_name: "Older Org" })]]);
    await page.goto("/dashboard/platform/billing");
    await expect(page.getByRole("table")).toContainText("Acme");

    await page.getByRole("button", { name: "Load more" }).click();

    await expect(page.getByRole("table")).toContainText("Older Org");
    await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  });

  test("the platform overview links to it", async ({ page }) => {
    await platformAdmin(page, [[record()]]);
    await page.goto("/dashboard/platform");

    await expect(page.getByRole("link", { name: /Billing/ }).first()).toHaveAttribute("href", "/dashboard/platform/billing");
  });
});
