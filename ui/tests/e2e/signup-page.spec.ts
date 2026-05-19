import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { SignupPage } from "../pages/signup-page.po";

test.describe("Signup Page", () => {
  test.describe.configure({ mode: "serial" });
  let signupPage: SignupPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    signupPage = new SignupPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptLogoutRequest();
    await dataSupportPage.auth.interceptSignupRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();

    await signupPage.goto();
  });

  test("should display signup form with all fields", async () => {
    await expect(signupPage.title()).toBeVisible();
    await expect(signupPage.fullNameField()).toBeVisible();
    await expect(signupPage.emailField()).toBeVisible();
    await expect(signupPage.passwordField()).toBeVisible();
    await expect(signupPage.confirmPasswordField()).toBeVisible();
    await expect(signupPage.submitAction()).toBeVisible();
  });

  test("should successfully create account", async ({ page }) => {
    await signupPage.signup(
      "Pending User",
      "pending@example.com",
      "StrongPass123",
    );

    await page.waitForURL("/dashboard");
    await expect(
      page.getByRole("heading", { name: /your team/i }),
    ).toBeVisible();
  });

  test("should show conflict error when signup fails", async ({ page }) => {
    await dataSupportPage.auth.interceptSignupRequest({
      success: false,
      status: 409,
      detail: "An account already exists for this email",
    });

    await signupPage.signup(
      "Pending User",
      "pending@example.com",
      "StrongPass123",
    );

    await expect(
      page.getByText("An account already exists for this email"),
    ).toBeVisible();
    await expect(page).toHaveURL("/signup");
  });
});
