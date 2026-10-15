import { expect, Page, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { PlatformWorkflowDataSupport } from "../pages/data-support/platform-workflow-data-support.po";
import { PlatformWorkflowSettingsPage } from "../pages/platform-workflow-settings-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

async function signIn(page: Page, admin = true) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: admin } });
  await data.users.interceptGetOrganizationsRequest();
}

test("Platform Admin enables and disables workflow authoring with a persisted choice", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformWorkflowDataSupport(page).intercept();
  await new DataSupport(page).platformMemory.intercept();
  const settings = new PlatformWorkflowSettingsPage(page);
  await page.goto("/dashboard/platform/settings");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(settings.toggle()).not.toBeChecked();
  await expect(settings.save()).toBeDisabled();
  await expect(page.getByText("Workflow execution is unavailable.")).toBeVisible();
  await settings.toggle().click();
  await settings.save().click();
  await expect(page.getByRole("status")).toHaveText("Workflow settings saved.");
  expect(mock.writes).toEqual([{ authoring_enabled: true }]);
  await page.reload();
  await expect(settings.toggle()).toBeChecked();
  await settings.toggle().click();
  await settings.save().click();
  await expect(page.getByRole("status")).toHaveText("Workflow settings saved.");
  await page.reload();
  await expect(settings.toggle()).not.toBeChecked();
  expect(mock.writes).toEqual([{ authoring_enabled: true }, { authoring_enabled: false }]);
  await page.screenshot({ path: test.info().outputPath("platform-workflow-settings.png"), fullPage: true });
  await page.getByRole("button", { name: "Agent Memory", exact: true }).click();
  await expect(page.getByTestId("saved-memory-model")).toBeVisible();
});

test("workflow setting cancel and failed save retain the correct choice", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformWorkflowDataSupport(page).intercept({ saveStatus: 503 });
  const settings = new PlatformWorkflowSettingsPage(page);
  await settings.goto();
  await settings.toggle().click();
  await settings.cancel();
  await expect(settings.toggle()).not.toBeChecked();
  expect(mock.writes).toEqual([]);
  await settings.toggle().click();
  await settings.save().click();
  await expect(page.getByRole("alert", { name: "Workflow setting error" })).toContainText("Workflow settings are unavailable");
  await expect(settings.toggle()).toBeChecked();
  mock.recover();
  await settings.save().click();
  await expect(page.getByRole("status")).toHaveText("Workflow settings saved.");
});

test("Organization Owner cannot fetch or change Platform workflow settings", async ({ page }) => {
  await signIn(page, false);
  const mock = await new PlatformWorkflowDataSupport(page).intercept();
  const settings = new PlatformWorkflowSettingsPage(page);
  await settings.goto();
  await expect(page.getByText("Platform admin access required")).toBeVisible();
  await expect(settings.toggle()).toHaveCount(0);
  expect(mock.reads).toEqual([]);
  expect(mock.writes).toEqual([]);
});

test("workflow settings read failure can be retried", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformWorkflowDataSupport(page).intercept({ readStatus: 503 });
  const settings = new PlatformWorkflowSettingsPage(page);
  await settings.goto();
  await expect(page.getByText("Could not load workflow settings")).toBeVisible();
  await expect(settings.toggle()).toHaveCount(0);
  mock.recover();
  await page.getByRole("button", { name: /retry|try again/i }).click();
  await expect(settings.toggle()).not.toBeChecked();
});
