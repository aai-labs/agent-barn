import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

const USERS_URL = "/dashboard/platform/users";

function user(index: number) {
  return {
    id: `11111111-1111-4111-8111-${String(index).padStart(12, "0")}`,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    full_name: `User ${index}`,
    email: `user-${index}@example.com`,
    is_platform_admin: false,
    email_verified_at: "2024-01-01T00:00:00Z",
  };
}

test.describe("Users Page — bounded platform authority", () => {
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetUsersRequest();
    await data.users.interceptCreateUserRequest();
    await data.users.interceptResendUserInviteRequest();
    await data.users.interceptPlatformPrivilegeRequest();
  });

  test("shows onboarding but keeps unsafe account mutations removed", async ({ page }) => {
    await page.goto(USERS_URL);

    await expect(page.getByRole("button", { name: /create user/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /delete user/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /reset password/i })).not.toBeVisible();
  });

  test("loads more users when the grid reaches its loading sentinel", async ({ page }) => {
    const firstPage = Array.from({ length: 20 }, (_, index) => user(index));
    await data.users.interceptGetUsersRequest({ pages: [firstPage, [user(20)]] });

    await page.goto(USERS_URL);
    await expect(page.getByText("User 0")).toBeVisible();

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));

    await expect(page.getByText("User 20")).toBeVisible();
  });

  test("creates a pending user with an initial organization and invitation", async ({
    page,
  }) => {
    await page.goto(USERS_URL);
    await page.getByRole("button", { name: /create user/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/set their own password/i)).toBeVisible();
    await expect(dialog.getByText(/do not need to be globally unique/i)).toBeVisible();
    await dialog.getByLabel("Email").fill("new@example.com");
    await dialog.getByLabel("Full name").fill("New User");
    await dialog
      .getByLabel("Initial organization name")
      .fill("New User Studio");
    await dialog.getByRole("button", { name: /create and invite/i }).click();

    await expect(
      dialog.getByRole("heading", { name: /invitation created/i }),
    ).toBeVisible();
    await expect(dialog.getByLabel("Invitation link")).toHaveValue(
      /set-password\?token=new-user-token/i,
    );
    await expect(page.getByText(/user and initial organization created/i)).toBeVisible();
  });

  test("resends enrollment for a pending user", async ({ page }) => {
    await page.goto(USERS_URL);
    await page.getByRole("button", { name: /resend invitation/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: /invitation resent/i }),
    ).toBeVisible();
    await expect(dialog.getByText(/previous invitation link is now invalid/i)).toBeVisible();
    await expect(dialog.getByLabel("Invitation link")).toHaveValue(
      /resent-user-token/i,
    );
  });

  test("granting Platform Privilege requires a reason and warns against secrets", async ({
    page,
  }) => {
    await page.goto(USERS_URL);

    await page
      .getByRole("button", { name: /grant platform admin/i })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: /grant Platform Privilege/i }),
    ).toBeVisible();
    await expect(dialog.getByText(/do not include passwords, tokens, API keys/i)).toBeVisible();
    const confirm = dialog.getByRole("button", { name: /grant privilege/i });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel(/reason/i).fill("Incident response rotation");
    await confirm.click();

    await expect(page.getByText(/Platform Privilege granted/i)).toBeVisible();
  });
});

test.describe("Platform user detail", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetPlatformUser();
  });

  test("renders user identity and the platform navigation", async ({ page }) => {
    await page.goto(`${USERS_URL}/11111111-1111-4111-8111-111111111111`);

    await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
    await expect(page.getByText("ada@example.com")).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: /users/i })).toHaveAttribute(
      "href",
      USERS_URL,
    );
  });

  test("shows a retryable error for an unavailable user", async ({ page }) => {
    await data.users.interceptGetPlatformUser({ status: 500 });
    await page.goto(`${USERS_URL}/11111111-1111-4111-8111-111111111111`);

    await expect(page.getByText(/couldn't load this user/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /retry/i })).toBeVisible();
  });
});
