import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

const USERS_URL = "/dashboard/platform/users";

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
      .getByRole("button", { name: /grant Platform Privilege/i })
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
