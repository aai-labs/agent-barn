import { expect, test } from "@playwright/test";

import authFixture from "../fixtures/auth.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { LoginPage } from "../pages/login-page.po";

test.describe("Login Page", () => {
  test.describe.configure({ mode: "serial" });
  let loginPage: LoginPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptLogoutRequest();
    await dataSupportPage.auth.interceptLoginRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();

    await loginPage.goto();
  });

  test("should display login form with all fields", async () => {
    await expect(loginPage.title()).toBeVisible();
    await expect(loginPage.emailField()).toBeVisible();
    await expect(loginPage.passwordField()).toBeVisible();
    await expect(loginPage.submitAction()).toBeVisible();
  });

  test("should successfully login with valid credentials", async ({ page }) => {
    await loginPage.login(
      authFixture.validUser.email,
      authFixture.validUser.password,
    );

    await page.waitForURL("/dashboard");
    await expect(
      page.getByRole("heading", { name: /your team/i }),
    ).toBeVisible();
  });

  test("should submit on Enter key", async ({ page }) => {
    await loginPage.loginWithEnter(
      authFixture.validUser.email,
      authFixture.validUser.password,
    );

    await page.waitForURL("/dashboard");
    await expect(
      page.getByRole("heading", { name: /your team/i }),
    ).toBeVisible();
  });

  test("should show error on invalid credentials", async ({ page }) => {
    await dataSupportPage.auth.interceptLoginRequest({
      success: false,
      detail: "Invalid email or password, please try again.",
    });

    await loginPage.login(
      authFixture.invalidUser.email,
      authFixture.invalidUser.password,
    );

    await expect(
      page.getByText("Invalid email or password, please try again."),
    ).toBeVisible();
    await expect(page).toHaveURL("/login");
  });
});
