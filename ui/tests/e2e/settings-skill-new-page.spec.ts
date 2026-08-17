import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import { mockCustomSkill } from "../pages/data-support/skill-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Settings — New skill page", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  let dataSupportPage: DataSupport;

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);
    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/new`);
  });

  test("starts from a SKILL.md entry point", async ({ page }) => {
    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");

    await expect(page.getByRole("button", { name: "SKILL.md", exact: true })).toBeVisible();
    await expect(page.getByLabel("Content of SKILL.md")).not.toBeEmpty();
  });

  test("can add a nested file", async ({ page }) => {
    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");

    await page.getByPlaceholder("helpers/notes.md").fill("helpers/notes.md");
    await page.getByRole("button", { name: "Add file" }).click();

    await expect(page.getByRole("button", { name: "notes.md", exact: true })).toBeVisible();
    await expect(page.getByLabel("Content of helpers/notes.md")).toBeVisible();
  });

  test("rejects a duplicate file path", async ({ page }) => {
    await page.getByPlaceholder("helpers/notes.md").fill("SKILL.md");
    await page.getByRole("button", { name: "Add file" }).click();

    await expect(page.getByText("A file with that path already exists.")).toBeVisible();
  });

  test("Create skill is disabled until a name is entered", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Create skill" })).toBeDisabled();

    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");

    await expect(page.getByRole("button", { name: "Create skill" })).toBeEnabled();
  });

  test("Cancel returns to the skills tab", async ({ page }) => {
    await page.getByRole("link", { name: "Cancel" }).click();

    await expect(page).toHaveURL(new RegExp(`/settings\\?tab=skills$`));
  });

  test("creating a skill navigates to its detail page", async ({ page }) => {
    const newSkillId = "cccccccc-1111-4ccc-8ccc-cccccccccccc";
    await dataSupportPage.skills.interceptCreateSkillRequest({
      skill: { ...mockCustomSkill, id: newSkillId, name: "test-skill", slug: "test-skill" },
    });
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: newSkillId,
      skill: { ...mockCustomSkill, id: newSkillId, name: "test-skill", slug: "test-skill" },
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({ skillId: newSkillId });

    await page.getByPlaceholder("e.g. my-tool").fill("test-skill");
    await page.getByRole("button", { name: "Create skill" }).click();

    await expect(page).toHaveURL(new RegExp(`/settings/skills/${newSkillId}$`));
  });

  test("shows the create error inline", async ({ page }) => {
    await dataSupportPage.skills.interceptCreateSkillRequest({
      status: 409,
      detail: "A skill with that name already exists.",
    });

    await page.getByPlaceholder("e.g. my-tool").fill("my-tool");
    await page.getByRole("button", { name: "Create skill" }).click();

    await expect(page.getByText("Could not create skill")).toBeVisible();
  });
});
