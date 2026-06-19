import { expect, test } from "@playwright/test";

import {
  mockCustomSkill,
  mockPlatformSkill,
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

  test("shows platform skill in the list", async ({ page }) => {
    await expect(page.getByText("github", { exact: true })).toBeVisible();
  });

  test("shows custom skill in the list", async ({ page }) => {
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
    await page.getByRole("button", { name: "View" }).first().click();

    await expect(page.getByRole("heading", { name: "github" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Close", exact: true })).toBeVisible();
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
      body: [mockPlatformSkill],
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

test.describe("Settings — Skills panel (pagination)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  let dataSupportPage: DataSupport;

  test.beforeEach(async ({ page }) => {
    dataSupportPage = new DataSupport(page);
    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
  });

  test("shows pagination controls when results exceed one page", async ({ page }) => {
    const manySkills = Array.from({ length: 15 }, (_, i) => ({
      ...mockPlatformSkill,
      id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(i).padStart(12, "0")}`,
      name: `skill-${i}`,
    }));
    await dataSupportPage.skills.interceptGetSkillsRequest({
      body: { page: 1, page_size: 15, total: 16, items: manySkills },
    });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByRole("button", { name: "Next", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Previous", exact: true })).toBeVisible();
  });

  test("pagination controls are hidden when all results fit on one page", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillsRequest();

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByRole("button", { name: "Next", exact: true })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Previous", exact: true })).not.toBeVisible();
  });

  test("clicking Next requests page 2 from the API", async ({ page }) => {
    const page1Skills = Array.from({ length: 15 }, (_, i) => ({
      ...mockPlatformSkill,
      id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(i).padStart(12, "0")}`,
      name: `skill-page1-${i}`,
    }));
    const page2Skills = [{ ...mockCustomSkill, name: "skill-page2-0" }];

    await page.route("**/api/v1/skills*", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/v1/skills") { await route.fallback(); return; }
      const pageNum = Number(url.searchParams.get("page") ?? "1");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          page: pageNum,
          page_size: 15,
          total: 16,
          items: pageNum === 1 ? page1Skills : page2Skills,
        }),
      });
    });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByText("skill-page1-0")).toBeVisible();

    await page.getByRole("button", { name: "Next", exact: true }).click();

    await expect(page.getByText("skill-page2-0")).toBeVisible();
    await expect(page.getByText("skill-page1-0")).not.toBeVisible();
  });

  test("search resets to page 1", async ({ page }) => {
    const page1Skills = Array.from({ length: 15 }, (_, i) => ({
      ...mockPlatformSkill,
      id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(i).padStart(12, "0")}`,
      name: `skill-${i}`,
    }));

    await page.route("**/api/v1/skills*", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/v1/skills") { await route.fallback(); return; }
      const search = url.searchParams.get("search")?.toLowerCase();
      const pageNum = Number(url.searchParams.get("page") ?? "1");
      const items = search
        ? page1Skills.filter((s) => s.name.includes(search))
        : pageNum === 1
          ? page1Skills
          : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ page: pageNum, page_size: 15, total: search ? items.length : 16, items }),
      });
    });

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Skills" }).click();

    // Advance to page 2.
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByText("2 / 2")).toBeVisible();

    // Typing in search should reset back to page 1.
    await page.getByLabel("Search skills").fill("skill-0");
    await expect(page.getByRole("button", { name: "Next", exact: true })).not.toBeVisible();
  });
});