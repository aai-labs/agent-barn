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

  test("built-in skill is read-only: no Edit or Delete, but a Fork for managers", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: MOCK_PLATFORM_SKILL_ID,
      skill: mockPlatformSkill,
      files: [{ path: "github_skill.md", content: "# GitHub" }],
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({ skillId: MOCK_PLATFORM_SKILL_ID });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_PLATFORM_SKILL_ID}`);

    await expect(page.getByRole("heading", { name: "github" })).toBeVisible();
    await expect(page.getByText("Built in")).toBeVisible();
    await expect(page.getByRole("button", { name: "Fork" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Edit/ })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).not.toBeVisible();
    await expect(page.getByLabel(/^Content of /)).toHaveText("# GitHub");
  });

  test("forking a built-in skill lands on the fork's draft editor with Save draft enabled", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: MOCK_PLATFORM_SKILL_ID,
      skill: mockPlatformSkill,
      files: [{ path: "github_skill.md", content: "# GitHub" }],
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({ skillId: MOCK_PLATFORM_SKILL_ID });
    await dataSupportPage.skills.interceptForkSkillRequest();
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skill: { ...mockCustomSkill, name: "github", entryPath: "github_skill.md", hasDraft: true },
      files: [{ path: "github_skill.md", content: "# GitHub" }],
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptUpdateSkillRequest();
    await dataSupportPage.skills.interceptUpdateSkillDraftRequest({
      files: [{ path: "github_skill.md", content: "# Edited fork" }],
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_PLATFORM_SKILL_ID}`);
    await page.getByRole("button", { name: "Fork" }).click();
    await page.getByRole("button", { name: "Fork skill" }).click();

    await expect(page).toHaveURL(new RegExp(`settings/skills/${MOCK_CUSTOM_SKILL_ID}\\?edit=1$`));
    const saveDraft = page.getByRole("button", { name: "Save draft" });
    await expect(saveDraft).toBeEnabled();
    const fileInput = page.getByLabel("Content of github_skill.md");
    await fileInput.fill("# Edited fork");
    await expect(page.getByRole("button", { name: "Discard" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).not.toBeVisible();
    await expect(fileInput).toHaveValue("# Edited fork");
    await saveDraft.click();
    await expect(fileInput).toHaveValue("# Edited fork");
  });

  test("custom skill shows Edit action with no lineage Delete", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);

    await expect(page.getByRole("heading", { name: mockCustomSkill.name })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).not.toBeVisible();
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

  test("clicking Edit starts a draft and shows Discard and Save draft (no Publish in the editor)", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await dataSupportPage.skills.interceptStartSkillDraftRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Edit" }).click();

    await expect(page.getByLabel("Content of SKILL.md")).toHaveValue("# My tool");
    await expect(page.getByRole("button", { name: "Discard" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save draft" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).not.toBeVisible();
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

  test("Publish from the read-only view publishes the draft", async ({ page }) => {
    let hasDraft = true;
    await page.route(`**/api/v1/organizations/*/skills/${MOCK_CUSTOM_SKILL_ID}/files`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...mockCustomSkill,
          hasDraft,
          files: [{ path: "SKILL.md", content: "# My tool" }],
        }),
      });
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();
    await page.route(`**/api/v1/organizations/*/skills/${MOCK_CUSTOM_SKILL_ID}/draft/publish`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      hasDraft = false;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ ...mockCustomSkill, version: 2, hasDraft: false }),
      });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);

    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).toBeVisible();
    await page.getByRole("button", { name: "Publish" }).click();
    await page.getByRole("button", { name: "Publish this version" }).click();

    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).not.toBeVisible();
  });

  test("version selector switches to a historical version's read-only content", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      versions: [
        { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z" },
        { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z" },
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

  test("history section lists versions with no restore action", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      versions: [
        { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z" },
        { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z" },
      ],
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Version history" }).click();

    await expect(page.getByText("Version 2")).toBeVisible();
    await expect(page.getByText("Version 1")).toBeVisible();
    await expect(page.getByText("Current")).toBeVisible();
    await expect(page.getByRole("button", { name: /restore/i })).not.toBeVisible();
  });

  test("history section deletes a historical version after confirmation", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    let versions: Record<string, unknown>[] = [
      { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z" },
      { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z" },
    ];
    await page.route(`**/api/v1/organizations/*/skills/${MOCK_CUSTOM_SKILL_ID}/versions`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(versions),
      });
    });
    let deleteCalled = false;
    await page.route(`**/api/v1/organizations/*/skills/${MOCK_CUSTOM_SKILL_ID}/versions/1`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      deleteCalled = true;
      versions = versions.filter((v) => v.version !== 1);
      await route.fulfill({ status: 204, body: "" });
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
    await page.getByRole("button", { name: "Version history" }).click();

    await expect(page.getByRole("button", { name: "Delete version 1" })).toBeEnabled();
    await page.getByRole("button", { name: "Delete version 1" }).click();
    await page.getByRole("button", { name: "Delete version" }).click();

    expect(deleteCalled).toBe(true);
    await expect(page.getByRole("button", { name: "Delete version 1" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Delete version 2" })).toBeVisible();
  });
});
