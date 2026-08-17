import { TEST_ORG_ID } from "../constants";
import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

const OWNER_USER_ID = "88888888-8888-4888-8888-888888888888";
const CREDENTIAL_ID = "3f1a7c22-5b8e-4d31-9a6f-2c4e8b0d1a55";

const BASE = `**/api/v1/organizations/${TEST_ORG_ID}/shared-credentials`;

// The drawer's Connect/Edit controls are gated on canManage, which needs a real
// OWNER/ADMIN membership; the default mocked context has organization_users: [].
function ownerContext() {
  const organization = {
    id: TEST_ORG_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    is_default: false,
    owner_email: "owner@example.com",
    owner_name: "Owner",
    allowed_models: ["*"],
  };
  return {
    id: OWNER_USER_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    full_name: "Org Owner",
    email: "owner@example.com",
    is_platform_admin: false,
    email_verified_at: "2024-01-01T00:00:00Z",
    organization_users: [
      {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        user_id: OWNER_USER_ID,
        organization_id: TEST_ORG_ID,
        role: "OWNER",
        organization,
      },
    ],
  };
}

const mockConfluenceCredential = {
  id: CREDENTIAL_ID,
  organizationId: TEST_ORG_ID,
  provider: "confluence",
  name: "Production Confluence",
  createdBy: null,
  agentCount: 0,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

async function interceptList(page: Page, items: unknown[]) {
  await page.route(`${BASE}?*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ page: 1, pageSize: 15, total: items.length, items }),
    });
  });
}

async function openSharedCredentials(page: Page) {
  await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
  await page.getByRole("button", { name: "Shared Credentials" }).click();
}

// FormField renders a bare <label> with no htmlFor, so getByLabel cannot resolve
// these inputs; target them within the drawer instead.
function drawerOf(page: Page) {
  const drawer = page.locator("aside.af-drawer-panel");
  return {
    drawer,
    providerSelect: drawer.locator("select.af-select"),
    name: drawer.getByPlaceholder("e.g. Production Jira"),
    siteUrl: drawer.getByPlaceholder("https://your-domain.atlassian.net"),
    email: drawer.getByPlaceholder("you@example.com"),
    apiToken: drawer.locator('input[type="password"]'),
    // exact: "Scoped token" otherwise also matches "Non-scoped token".
    scoped: drawer.getByRole("radio", { name: "Scoped token", exact: true }),
    nonScoped: drawer.getByRole("radio", { name: "Non-scoped token", exact: true }),
  };
}

async function fillConfluenceExceptAuthType(page: Page) {
  const f = drawerOf(page);
  await f.providerSelect.selectOption("confluence");
  await f.name.fill("Prod Confluence");
  await f.siteUrl.fill("https://x.atlassian.net");
  await f.email.fill("admin@example.com");
  await f.apiToken.fill("secret-token");
  return f;
}

test.describe("Settings — Shared credentials drawer", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest({
      userContext: ownerContext(),
    });
    await dataSupportPage.users.interceptGetOrganizationsRequest();
  });

  test("Authentication Type renders as radio inputs, not a text box", async ({ page }) => {
    await interceptList(page, []);
    await openSharedCredentials(page);
    await page.getByRole("button", { name: /connect credential/i }).click();

    const f = drawerOf(page);
    await f.providerSelect.selectOption("confluence");

    await expect(f.scoped).toBeVisible();
    await expect(f.nonScoped).toBeVisible();
  });

  test("Create stays disabled until Authentication Type is selected", async ({ page }) => {
    await interceptList(page, []);
    await openSharedCredentials(page);
    await page.getByRole("button", { name: /connect credential/i }).click();

    const f = await fillConfluenceExceptAuthType(page);
    const create = page.getByRole("button", { name: "Create credential" });

    await expect(create).toBeDisabled();

    await f.scoped.check();

    await expect(create).toBeEnabled();
  });

  test("submits use_scoped_token as a boolean, not a string", async ({ page }) => {
    await interceptList(page, []);
    await page.route(BASE, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(mockConfluenceCredential),
      });
    });

    await openSharedCredentials(page);
    await page.getByRole("button", { name: /connect credential/i }).click();

    const f = await fillConfluenceExceptAuthType(page);
    await f.scoped.check();

    const [request] = await Promise.all([
      page.waitForRequest(
        (r) => r.method() === "POST" && r.url().includes("/shared-credentials"),
      ),
      page.getByRole("button", { name: "Create credential" }).click(),
    ]);

    const body = request.postDataJSON() as { content?: Record<string, unknown> };
    expect(body.content?.use_scoped_token).toBe(true);
  });

  test("renaming without touching credential fields sends no content", async ({ page }) => {
    await interceptList(page, [mockConfluenceCredential]);
    await page.route(`${BASE}/${CREDENTIAL_ID}`, async (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...mockConfluenceCredential, name: "Renamed Confluence" }),
      });
    });

    await openSharedCredentials(page);
    await page.getByRole("button", { name: "View" }).click();
    await page.getByRole("button", { name: "Edit credential" }).click();

    await drawerOf(page).name.fill("Renamed Confluence");

    const save = page.getByRole("button", { name: "Save changes" });
    await expect(save).toBeEnabled();

    const [request] = await Promise.all([
      page.waitForRequest(
        (r) => r.method() === "PATCH" && r.url().includes("/shared-credentials/"),
      ),
      save.click(),
    ]);

    const body = request.postDataJSON() as { name?: string; content?: unknown };
    expect(body.name).toBe("Renamed Confluence");
    expect(body.content).toBeUndefined();
  });
});
