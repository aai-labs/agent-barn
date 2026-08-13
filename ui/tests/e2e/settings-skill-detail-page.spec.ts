import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import {
  mockCustomSkill,
  mockPlatformSkill,
  MOCK_CUSTOM_SKILL_ID,
  MOCK_PLATFORM_SKILL_ID,
} from "../pages/data-support/skill-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Settings — Skill detail page", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  let dataSupportPage: DataSupport;

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);
    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
  });

  test("built-in skill is read-only with no Edit or Delete actions", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: MOCK_PLATFORM_SKILL_ID,
      skill: mockPlatformSkill,
      files: [{ path: "github_skill.md", content: "# GitHub" }],
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({ skillId: MOCK_PLATFORM_SKILL_ID });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_PLATFORM_SKILL_ID}`);

    await expect(page.getByRole("heading", { name: "github" })).toBeVisible();
    await expect(page.getByText("Built in")).toBeVisible();
    await expect(page.getByRole("button", { name: /^Edit/ })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).not.toBeVisible();
    await expect(page.getByLabel(/^Content of /)).toHaveText("# GitHub");
  });

  test("custom skill shows Edit and Delete actions", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);

    await expect(page.getByRole("heading", { name: mockCustomSkill.name })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  test("back link returns to the skills tab", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await expect(page.getByRole("link", { name: "Skills" })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=skills`,
    );
  });

  test("clicking Edit starts a draft and shows Discard, Save draft, and Publish", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptStartSkillDraftRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Edit" }).click();

    await expect(page.getByLabel("Content of SKILL.md")).toHaveValue("# My tool");
    await expect(page.getByRole("button", { name: "Discard" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save draft" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).toBeVisible();
  });

  test("Save draft calls the draft and metadata update endpoints", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptStartSkillDraftRequest();
    await dataSupportPage.skills.interceptUpdateSkillRequest();

    let draftUpdateCalled = false;
    await page.route(`**/api/v1/organizations/*/skills/${MOCK_CUSTOM_SKILL_ID}/draft`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      draftUpdateCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          skill_id: MOCK_CUSTOM_SKILL_ID,
          files: [{ path: "SKILL.md", content: "# Edited" }],
          source_version: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Content of SKILL.md").fill("# Edited");
    await page.getByRole("button", { name: "Save draft" }).click();

    await expect(page.getByLabel("Content of SKILL.md")).toHaveValue("# Edited");
    expect(draftUpdateCalled).toBe(true);
  });

  test("Discard removes the draft and returns to read-only view", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptStartSkillDraftRequest();
    await dataSupportPage.skills.interceptDiscardSkillDraftRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Edit" }).click();
    await expect(page.getByRole("button", { name: "Discard" })).toBeVisible();

    await page.getByRole("button", { name: "Discard" }).click();
    await page.getByRole("button", { name: "Discard draft" }).click();

    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Discard" })).not.toBeVisible();
  });

  test("Publish calls the publish endpoint and returns to read-only view", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptStartSkillDraftRequest();
    await dataSupportPage.skills.interceptUpdateSkillRequest();
    await dataSupportPage.skills.interceptUpdateSkillDraftRequest();
    await dataSupportPage.skills.interceptPublishSkillDraftRequest({
      skill: { ...mockCustomSkill, version: 2, hasDraft: false },
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("button", { name: "Publish this version" }).click();

    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
  });

  test("version selector switches to a historical version's read-only content", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      versions: [
        { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z", restored_from_version: null },
        { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z", restored_from_version: null },
      ],
    });
    await dataSupportPage.skills.interceptGetSkillVersionRequest({
      version: 1,
      files: [{ path: "SKILL.md", content: "# Version one" }],
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("combobox", { name: "Version" }).click();
    await page.getByRole("option", { name: "Version v1", exact: true }).click();

    await expect(page.getByLabel("Content of SKILL.md")).toHaveText("# Version one");
  });

  test("history section lists versions and restores an older one as a draft", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      versions: [
        { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z", restored_from_version: null },
        { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z", restored_from_version: null },
      ],
    });
    await dataSupportPage.skills.interceptStartSkillDraftRequest({
      files: [{ path: "SKILL.md", content: "# Version one" }],
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Version history" }).click();

    await expect(page.getByText("Version 2")).toBeVisible();
    await expect(page.getByText("Version 1")).toBeVisible();
    await expect(page.getByText("Current")).toBeVisible();

    await page.getByRole("button", { name: "Restore as draft" }).click();

    await expect(page.getByRole("button", { name: "Publish" })).toBeVisible();
    await expect(page.getByLabel("Content of SKILL.md")).toHaveValue("# Version one");
  });

  test("Delete confirmation deletes the skill and returns to the skills list", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptDeleteSkillRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({ body: [mockPlatformSkill] });
    await dataSupportPage.agents.interceptGetTemplatesRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("button", { name: "Delete skill" }).click();

    await expect(page).toHaveURL(new RegExp(`/settings\\?tab=skills$`));
  });
});
