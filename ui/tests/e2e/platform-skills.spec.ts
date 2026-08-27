import { expect, test } from "@playwright/test";

import {
  MOCK_PLATFORM_SKILL_ID,
  mockPlatformSkill,
} from "../pages/data-support/skill-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Platform Skills", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  let dataSupportPage: DataSupport;

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);
    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.skills.interceptGetPlatformSkillsRequest();
    await page.goto("/dashboard/platform/skills");
  });

  test("renders platform skills as cards", async ({ page }) => {
    const githubCard = page.getByRole("link", { name: /github/ });

    await expect(githubCard).toBeVisible();
    await expect(githubCard.getByText("Platform")).toBeVisible();
    await expect(githubCard.getByText("Built in")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add", exact: true })).toHaveCount(0);
  });

  test("card detail returns to the platform skills list", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: MOCK_PLATFORM_SKILL_ID,
      skill: mockPlatformSkill,
      files: [{ path: "github_skill.md", content: "# GitHub" }],
      scope: "platform",
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      skillId: MOCK_PLATFORM_SKILL_ID,
      scope: "platform",
    });

    await page.getByRole("link", { name: /github/ }).click();

    await expect(page).toHaveURL(new RegExp(`/dashboard/platform/skills/${MOCK_PLATFORM_SKILL_ID}$`));
    await expect(page.getByRole("heading", { name: mockPlatformSkill.name })).toBeVisible();

    const backLink = page.getByRole("link", { name: "Skills" }).filter({
      has: page.locator("svg"),
    });
    await expect(backLink).toHaveAttribute("href", "/dashboard/platform/skills");
    await backLink.click();
    await expect(page).toHaveURL(/\/dashboard\/platform\/skills$/);
    await expect(page.getByRole("link", { name: /github/ })).toBeVisible();
  });
});
