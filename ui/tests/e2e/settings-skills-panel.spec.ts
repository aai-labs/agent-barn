import { expect, test } from "@playwright/test";

import {
  mockCustomSkill,
  MOCK_CUSTOM_SKILL_ID,
} from "../pages/data-support/skill-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Settings — Skills panel", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest();

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();
  });

  test("shows platform hint text", async ({ page }) => {
    await expect(
      page.getByText(/Platform skills are provided by AAI Labs/),
    ).toBeVisible();
  });

  test("shows New skill button", async ({ page }) => {
    await expect(page.getByRole("button", { name: /new skill/i })).toBeVisible();
  });

  test("shows Platform section with platform skill", async ({ page }) => {
    await expect(page.locator("div").filter({ hasText: /^Platform$/ })).toBeVisible();
    await expect(page.getByText("github", { exact: true })).toBeVisible();
  });

  test("shows Custom section with custom skill", async ({ page }) => {
    await expect(page.locator("div").filter({ hasText: /^Custom$/ })).toBeVisible();
    await expect(page.getByText("my-tool")).toBeVisible();
  });

  test("platform skill has no edit or delete buttons", async ({ page }) => {
    // Only the custom skill row has Edit and Delete buttons
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(1);
    // The Platform badge appears next to the platform skill
    await expect(page.getByText("Platform", { exact: true })).toBeVisible();
  });

  test("custom skill shows Edit and Delete buttons", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("clicking New skill opens create dialog", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();

    await expect(page.getByText("New skill")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create skill" })).toBeVisible();
  });

  test("create skill dialog shows file error when submitted without a zip", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();
    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");
    await page.getByRole("button", { name: "Create skill" }).click();

    await expect(page.getByText("A zip file is required.")).toBeVisible();
  });

  test("create skill dialog can be cancelled", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();
    await expect(page.getByText("New skill")).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(page.getByText("New skill")).not.toBeVisible();
  });

  test("clicking Edit opens dialog pre-populated with skill name", async ({ page }) => {
    await page.getByRole("button", { name: "Edit" }).click();

    await expect(page.getByText("Edit skill")).toBeVisible();
    await expect(page.getByPlaceholder("e.g. my-tool")).toHaveValue(mockCustomSkill.name);
  });

  test("edit dialog shows hint to keep existing zip", async ({ page }) => {
    await page.getByRole("button", { name: "Edit" }).click();

    await expect(page.getByText("Leave empty to keep the existing zip.")).toBeVisible();
  });

  test("clicking Delete shows confirmation row", async ({ page }) => {
    await page.getByRole("button", { name: "Delete" }).click();

    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Delete", exact: true }),
    ).toBeVisible();
  });

  test("cancelling delete restores the normal skill row", async ({ page }) => {
    await page.getByRole("button", { name: "Delete" }).click();
    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("confirming delete calls the delete API and removes the skill", async ({ page }) => {
    await dataSupportPage.skills.interceptDeleteSkillRequest({
      skillId: MOCK_CUSTOM_SKILL_ID,
    });
    // After delete, re-intercept GET to return only the platform skill
    await dataSupportPage.skills.interceptGetSkillsRequest({
      body: [
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          organizationId: null,
          name: "github",
          source: "aai_cli",
          requiredProviders: ["github"],
          toolsPointer: null,
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-01T00:00:00Z",
        },
      ],
    });

    await page.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page.getByText("my-tool")).not.toBeVisible();
  });
});

test.describe("Settings — Skills panel (empty state)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("shows empty state when no skills exist", async ({ page }) => {
    const dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({ body: [] });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByText("No skills yet")).toBeVisible();
    await expect(
      page.getByText("Create your first custom skill to get started."),
    ).toBeVisible();
  });

  test("shows error state when skills API fails", async ({ page }) => {
    const dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({
      status: 500,
      detail: "Skills service unavailable",
    });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByText("We couldn't load skills")).toBeVisible();
  });
});