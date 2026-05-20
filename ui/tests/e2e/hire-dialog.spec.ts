import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

test.describe("Hire Dialog", () => {
  test.describe.configure({ mode: "serial" });
  let dashboardPage: DashboardPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentsRequest();

    await dashboardPage.goto();
    await page.getByRole("button", { name: /hire a teammate/i }).click();
  });

  test("should open the hire dialog on step 1", async ({ page }) => {
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
    await expect(page.getByText(/step 1 of/i)).toBeVisible();
  });

  test("should advance to Slack choice step", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Set up your Slack app")).toBeVisible();
    await expect(page.getByText(/step 2 of/i)).toBeVisible();
  });

  test("should skip bot builder when choosing existing app", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Connect Slack")).toBeVisible();
    await expect(page.getByText(/step 3 of 4/i)).toBeVisible();
  });

  test("should go through bot builder when choosing new bot", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Build your Slack bot")).toBeVisible();
    await expect(page.getByText(/step 3 of 5/i)).toBeVisible();
  });

  test("should show manifest in bot builder step", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("Set up a new Slack bot").click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("Generated manifest")).toBeVisible();
    await expect(page.getByRole("link", { name: /create app/i })).toBeVisible();
  });

  test("should advance to details step (path: skip bot builder)", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByText("A few details and we'll get them set up.")).toBeVisible();
    await expect(page.getByText(/step 4 of 4/i)).toBeVisible();
  });

  test("should show model dropdown with one option", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByText("I already have a Slack app").click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    await expect(page.getByRole("combobox", { name: /model/i })).toBeVisible();
    await expect(page.getByRole("option", { name: /gpt-5 mini/i })).toBeAttached();
  });

  test("should navigate back through steps", async ({ page }) => {
    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page.getByText("Set up your Slack app")).toBeVisible();

    await page.getByRole("button", { name: /back/i }).click();
    await expect(page.getByText("What kind of teammate do you need?")).toBeVisible();
  });

  test("should close the hire dialog", async ({ page }) => {
    await page.getByRole("button", { name: /cancel/i }).click();

    await expect(page.getByText("What kind of teammate do you need?")).not.toBeVisible();
  });
});
