import { expect, Page, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { PlatformMemorySettingsPage } from "../pages/platform-memory-settings-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

async function signIn(page: Page, admin = true) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: admin } });
  await data.users.interceptGetOrganizationsRequest();
}

test("Platform Admin can search and save the shared memory model", async ({ page }) => {
  await signIn(page);
  const settings = new PlatformMemorySettingsPage(page);
  const mock = await settings.intercept();
  await settings.goto();
  await expect(page.getByRole("heading", { name: "Platform Settings" })).toBeVisible();
  await expect(settings.model()).toContainText("GPT-4.1 mini");
  await expect(settings.save()).toBeDisabled();
  await expect(page.getByText("Each Agent keeps its own chat model.", { exact: false })).toBeVisible();
  await settings.choose("Alternate model");
  await settings.save().click();
  await expect(page.getByRole("status")).toContainText("Memory processing model saved");
  expect(mock.writes).toEqual([{ model: "openrouter/anthropic/alternate" }]);
  await page.reload();
  await expect(settings.model()).toContainText("Alternate model");
});

test("Organization Owner cannot open Platform Settings or fetch the memory setting", async ({ page }) => {
  await signIn(page, false);
  const settings = new PlatformMemorySettingsPage(page);
  const mock = await settings.intercept();
  await settings.goto();
  await expect(page.getByText("Platform admin access required")).toBeVisible();
  await expect(settings.model()).not.toBeVisible();
  expect(mock.writes).toEqual([]);
  expect(mock.reads).toEqual([]);
});

test("failed save preserves the choice and supports retry", async ({ page }) => {
  await signIn(page);
  const settings = new PlatformMemorySettingsPage(page);
  const mock = await settings.intercept({ saveStatus: 503 });
  await settings.goto();
  await settings.choose("Alternate model");
  await settings.save().click();
  await expect(page.getByRole("alert").filter({ hasText: "Your setting was not changed" })).toContainText("Your setting was not changed");
  await expect(settings.model()).toContainText("Alternate model");
  mock.allowSave();
  await settings.save().click();
  await expect(page.getByRole("status")).toContainText("saved");
});

test("unavailable catalog prevents saving and shows retry", async ({ page }) => {
  await signIn(page);
  const settings = new PlatformMemorySettingsPage(page);
  await settings.intercept({ modelsStatus: 503 });
  await settings.goto();
  await expect(page.getByRole("button", { name: "Retry models" })).toBeVisible();
  await expect(settings.model()).toBeDisabled();
  await expect(settings.save()).toBeDisabled();
});
