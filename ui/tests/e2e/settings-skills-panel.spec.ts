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

  test("shows search input and source filter", async ({ page }) => {
    await expect(page.getByLabel("Search skills")).toBeVisible();
    await expect(page.getByLabel("Filter by source")).toBeVisible();
  });

  test("shows New skill button right-aligned in toolbar", async ({ page }) => {
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

  test("both platform and custom skill rows have only a View button", async ({ page }) => {
    await expect(page.getByRole("button", { name: "View" })).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
  });

  test("search filters the list", async ({ page }) => {
    await page.getByLabel("Search skills").fill("github");

    await expect(page.getByText("github", { exact: true })).toBeVisible();
    await expect(page.getByText("my-tool")).not.toBeVisible();
  });

  test("source filter narrows to platform skills", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await page.getByRole("menuitemradio", { name: "Platform" }).click();

    await expect(page.getByText("github", { exact: true })).toBeVisible();
    await expect(page.getByText("my-tool")).not.toBeVisible();
  });

  test("source filter narrows to custom skills", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await page.getByRole("menuitemradio", { name: "Custom" }).click();

    await expect(page.getByText("my-tool")).toBeVisible();
    await expect(page.getByText("github", { exact: true })).not.toBeVisible();
  });

  test("search with no matches shows 'No skills match'", async ({ page }) => {
    await page.getByLabel("Search skills").fill("xyznonexistent");

    await expect(page.getByText("No skills match.")).toBeVisible();
  });

  test("clicking View on platform skill opens the drawer in read-only mode", async ({ page }) => {
    await page.getByRole("button", { name: "View" }).click();

    await expect(page.getByRole("heading", { name: "github" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).not.toBeVisible();
  });

  test("clicking New skill opens create drawer", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();

    await expect(page.getByRole("heading", { name: "New skill" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create skill" })).toBeVisible();
  });

  test("create skill drawer shows file error when submitted without a zip", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();
    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");
    await page.getByRole("button", { name: "Create skill" }).click();

    await expect(page.getByText("A zip file is required.")).toBeVisible();
  });

  test("create skill drawer can be cancelled", async ({ page }) => {
    await page.getByRole("button", { name: /new skill/i }).click();
    await expect(page.getByRole("heading", { name: "New skill" })).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(page.getByRole("heading", { name: "New skill" })).not.toBeVisible();
  });

  test("clicking View on custom skill opens drawer with Edit skill and Delete buttons", async ({
    page,
  }) => {
    // Custom skill is the second View button (platform is first)
    await page.getByRole("button", { name: "View" }).nth(1).click();

    await expect(page.getByRole("heading", { name: mockCustomSkill.name })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit skill" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("clicking Edit skill in drawer shows edit form pre-populated with skill name", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "View" }).nth(1).click();
    await page.getByRole("button", { name: "Edit skill" }).click();

    await expect(page.getByText("Edit skill")).toBeVisible();
    await expect(page.getByPlaceholder("e.g. my-tool")).toHaveValue(mockCustomSkill.name);
  });

  test("edit form in drawer shows hint to keep existing zip", async ({ page }) => {
    await page.getByRole("button", { name: "View" }).nth(1).click();
    await page.getByRole("button", { name: "Edit skill" }).click();

    await expect(page.getByText("Leave empty to keep the existing zip.")).toBeVisible();
  });

  test("clicking Delete in drawer shows confirmation", async ({ page }) => {
    await page.getByRole("button", { name: "View" }).nth(1).click();
    await page.getByRole("button", { name: "Delete" }).click();

    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete", exact: true })).toBeVisible();
  });

  test("cancelling delete in drawer returns to view mode", async ({ page }) => {
    await page.getByRole("button", { name: "View" }).nth(1).click();
    await page.getByRole("button", { name: "Delete" }).click();
    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(
      page.getByText(`Delete ${mockCustomSkill.name}? This cannot be undone.`),
    ).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Edit skill" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("confirming delete calls the delete API and closes the drawer", async ({ page }) => {
    await dataSupportPage.skills.interceptDeleteSkillRequest({
      skillId: MOCK_CUSTOM_SKILL_ID,
    });
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

    await page.getByRole("button", { name: "View" }).nth(1).click();
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
    await dataSupportPage.agents.interceptGetTemplatesRequest();
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
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({
      status: 500,
      detail: "Skills service unavailable",
    });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByText("We couldn't load skills")).toBeVisible();
  });
});