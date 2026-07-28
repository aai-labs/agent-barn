import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ORG_A_ID,
  ORG_B_ID,
} from "../pages/data-support/organization-data-support.po";

const ORGS_URL = "/dashboard/organizations";
const DETAIL_URL = `/dashboard/${ORG_A_ID}/members`;

function twoOrgs() {
  return [
    {
      id: ORG_A_ID,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      name: "AAI Labs",
      description: "Starter organization",
      is_default: false,
      owner_email: "owner@example.com",
      owner_name: "Grace Hopper",
    },
    {
      id: ORG_B_ID,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      name: "Globex",
      description: "Second organization",
      is_default: false,
      owner_email: "hank@globex.com",
      owner_name: "Hank Scorpio",
    },
  ];
}

test.describe("Organizations — list & create (platform_admin)", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptListOrganizations();
    await data.organizations.interceptCreateOrganization();
  });

  test("renders the organizations list", async ({ page }) => {
    await page.goto(ORGS_URL);
    await expect(
      page.getByRole("heading", { name: /organizations/i }),
    ).toBeVisible();
    await expect(page.getByText("AAI Labs").first()).toBeVisible();
  });

  test("platform_admin creates an org and sees the owner invite link", async ({
    page,
  }) => {
    await page.goto(ORGS_URL);

    await page.getByRole("button", { name: /create organization/i }).click();
    await expect(
      page.getByRole("heading", { name: /^create organization$/i }),
    ).toBeVisible();

    await page.getByLabel("Name", { exact: true }).fill("New Org");
    await page.getByLabel(/owner email/i).fill("founder@acme.com");
    await page.getByRole("button", { name: /^create$/i }).click();

    await expect(
      page.getByRole("heading", { name: /organization created/i }),
    ).toBeVisible();
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator("input[readonly]")).toHaveValue(
      /set-password\?token=/,
    );
  });
});

test.describe("Organization detail — delete", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptListOrganizations();
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptDeleteOrganization();
    await data.organizations.interceptGetMembers();
  });

  test("shows org details and members", async ({ page }) => {
    await page.goto(DETAIL_URL);
    await expect(
      page.getByRole("heading", { name: "AAI Labs" }),
    ).toBeVisible();
    await expect(page.getByText("Starter organization")).toBeVisible();
    await expect(page.getByText("ada@example.com")).toBeVisible();
  });

  test("delete requires typing the org name, then confirms", async ({
    page,
  }) => {
    await page.goto(DETAIL_URL);

    await page
      .getByRole("button", { name: /delete organization/i })
      .click();

    const dialog = page.getByRole("dialog");
    const confirm = dialog.getByRole("button", {
      name: /delete organization/i,
    });
    await expect(confirm).toBeDisabled();

    await dialog.getByLabel(/confirm organization name/i).fill("AAI Labs");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(page.getByText(/organization deleted/i)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${ORGS_URL}$`));
  });
});

test.describe("Organization detail — members", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptListOrganizations();
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptGetMembers();
    await data.organizations.interceptAddMember();
    await data.organizations.interceptChangeMemberRole();
    await data.organizations.interceptRemoveMember();
  });

  test("adds a member and surfaces the invite link", async ({ page }) => {
    await page.goto(DETAIL_URL);

    await page.getByRole("button", { name: /add member/i }).click();
    await page.getByLabel(/email/i).fill("teammate@example.com");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /add member/i })
      .click();

    await expect(
      page.getByRole("heading", { name: /member invited/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("dialog").locator("input[readonly]"),
    ).toHaveValue(/set-password\?token=/);
  });

  test("promotes a member to admin via the actions menu", async ({ page }) => {
    await page.goto(DETAIL_URL);

    await page.getByRole("button", { name: /member actions/i }).click();
    await page.getByRole("button", { name: /make admin/i }).click();

    // Confirm in the dialog before the change is applied.
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /make admin/i })
      .click();

    await expect(page.getByText(/is now admin/i)).toBeVisible();
  });

  test("removes a member after confirmation", async ({ page }) => {
    await page.goto(DETAIL_URL);

    await page.getByRole("button", { name: /member actions/i }).click();
    await page.getByRole("button", { name: /remove from org/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/remove member/i)).toBeVisible();
    await dialog.getByRole("button", { name: /^remove$/i }).click();

    await expect(page.getByText(/member removed/i)).toBeVisible();
  });
});

test.describe("Org switcher on the detail page", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptListOrganizations({ items: twoOrgs() });
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptGetMembers();
  });

  test("switching org navigates to the selected org's page", async ({ page }) => {
    await page.goto(DETAIL_URL);

    const switcher = page.locator('button[aria-haspopup="listbox"]');
    await switcher.click();
    await page
      .getByRole("listbox")
      .getByRole("option", { name: /globex/i })
      .click();

    await expect(page).toHaveURL(new RegExp(ORG_B_ID));
  });
});

test.describe("Org switcher — manage page for a member-only org", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  // Owner of org A, plain member of org B (non-platform_admin).
  function ownerOfAMemberOfB() {
    const [orgA, orgB] = twoOrgs();
    const userId = "44444444-4444-4444-8444-444444444444";
    const membership = (organization: unknown, role: string, id: string) => ({
      id,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      user_id: userId,
      organization_id: (organization as { id: string }).id,
      role,
      organization,
    });
    return {
      id: userId,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      full_name: "Grace Hopper",
      email: "owner-a@example.com",
      is_platform_admin: false,
      email_verified_at: "2024-01-01T00:00:00Z",
      organization_users: [
        membership(orgA, "OWNER", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        membership(orgB, "MEMBER", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
      ],
    };
  }

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: ownerOfAMemberOfB(),
    });
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptGetMembers();
    await data.agents.interceptGetAgentsRequest();
  });

  test("switching to an org where I'm only a member leaves the manage page for that org's home, not a 403 screen", async ({
    page,
  }) => {
    await page.goto(DETAIL_URL); // org A manage page (I'm the owner)
    await expect(page.getByRole("heading", { name: /AAI Labs/i })).toBeVisible();

    const switcher = page.locator('button[aria-haspopup="listbox"]');
    await switcher.click();
    await page
      .getByRole("listbox")
      .getByRole("option", { name: /globex/i })
      .click();

    // The guard redirects to org B's home instead of /members (which would 403).
    await expect(page).toHaveURL(new RegExp(`/dashboard/${ORG_B_ID}$`));
    await expect(page).not.toHaveURL(/\/members/);
  });
});

test.describe("Org switcher (platform_admin)", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.organizations.interceptListOrganizations({ items: twoOrgs() });
  });

  test("lists all orgs and switches the active one", async ({ page }) => {
    await page.goto(ORGS_URL);

    const switcher = page.locator('button[aria-haspopup="listbox"]');
    await expect(switcher).toContainText("AAI Labs");

    await switcher.click();
    const listbox = page.getByRole("listbox");
    await expect(listbox.getByRole("option", { name: /globex/i })).toBeVisible();

    await listbox.getByRole("option", { name: /globex/i }).click();
    await expect(switcher).toContainText("Globex");
  });
});

test.describe("Set password (accept invite)", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.auth.interceptLogoutRequest();
    // An invitee follows the link while logged OUT. The page must be public: a 401 from
    // /auth/me must NOT bounce them to /login (regression — it used to).
    await data.users.interceptGetUserContextRequest({ unauthorized: true });
    await data.organizations.interceptSetPassword();
  });

  test("rejects a link with no token", async ({ page }) => {
    await page.goto("/set-password");
    await expect(page.getByText(/invalid invite link/i)).toBeVisible();
  });

  test("sets a password from a valid invite token", async ({ page }) => {
    await page.goto("/set-password?token=invite-token-123");

    await page.getByLabel(/full name/i).fill("Jane Doe");
    await page.getByLabel(/^new password$/i).fill("StrongPass123");
    await page.getByLabel(/^confirm password$/i).fill("StrongPass123");

    // Tie the assertion to the durable signals — the set-password POST completing and
    // the redirect — rather than the success toast, which is created in the same tick as
    // router.push("/login") and can be dropped on a slow (CI) renderer mid-navigation.
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/v1/auth/set-password") &&
          r.request().method() === "POST",
      ),
      page.getByRole("button", { name: /^set password$/i }).click(),
    ]);

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByText(/please log in to continue/i)).toBeVisible();
  });
});

test.describe("Forgot / reset password", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.auth.interceptLogoutRequest();
    // Public pages: reached while logged out, so a 401 must not redirect to /login.
    await data.users.interceptGetUserContextRequest({ unauthorized: true });
    await data.auth.interceptForgotPasswordRequest();
    await data.auth.interceptResetPasswordRequest();
  });

  test("forgot password shows a check-your-email confirmation", async ({ page }) => {
    await page.goto("/forgot-password");

    await page.getByLabel(/email/i).fill("someone@example.com");
    await page.getByRole("button", { name: /send reset link/i }).click();

    await expect(page.getByText(/check your email/i)).toBeVisible();
    await expect(page.getByText("someone@example.com")).toBeVisible();
  });

  test("reset password rejects a link with no token", async ({ page }) => {
    await page.goto("/reset-password");
    await expect(page.getByText(/invalid reset link/i)).toBeVisible();
  });

  test("resets a password from a valid token", async ({ page }) => {
    await page.goto("/reset-password?token=reset-token-123");

    await page.getByLabel(/^new password$/i).fill("StrongPass123");
    await page.getByLabel(/^confirm password$/i).fill("StrongPass123");
    await page.getByRole("button", { name: /^reset password$/i }).click();

    await expect(page.getByText(/please log in to continue/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });
});
