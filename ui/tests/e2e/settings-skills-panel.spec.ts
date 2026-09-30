import { TEST_ORG_ID } from "../constants";
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    // The Settings page opens on the Agents tab.
    await dataSupportPage.organizations.interceptAgentSettings();
    await dataSupportPage.skills.interceptGetSkillsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
    await page.getByRole("button", { name: "Skills" }).click();
  });

  test("shows built-in skills hint text", async ({ page }) => {
    await expect(
      page.getByText(/Built-in skills are provided by AAI Labs/),
    ).toBeVisible();
  });

  test("does not show an organization avatar in the settings header", async ({ page }) => {
    await expect(page.getByText("AL", { exact: true })).toHaveCount(0);
  });

  test("shows search input and source filter", async ({ page }) => {
    await expect(page.getByLabel("Search skills")).toBeVisible();
    await expect(page.getByLabel("Filter by source")).toBeVisible();
  });

  test("shows New skill button right-aligned in toolbar", async ({ page }) => {
    await expect(page.getByRole("link", { name: /new skill/i })).toBeVisible();
  });

  test("shows platform skill as a card labeled Built in", async ({ page }) => {
    await expect(page.getByRole("link", { name: /github/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /github/ }).getByText("Built in")).toBeVisible();
  });

  test("shows custom skill as a card labeled Custom", async ({ page }) => {
    await expect(page.getByRole("link", { name: /my-tool/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /my-tool/ }).getByText("Custom")).toBeVisible();
  });

  test("source filter dropdown offers Built in instead of Platform", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await expect(page.getByRole("menuitemradio", { name: "Built in" })).toBeVisible();
  });

  test("search filters the cards", async ({ page }) => {
    await page.getByLabel("Search skills").fill("github");

    await expect(page.getByRole("link", { name: /github/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /my-tool/ })).not.toBeVisible();
  });

  test("source filter narrows to built-in skills", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await page.getByRole("menuitemradio", { name: "Built in" }).click();

    await expect(page.getByRole("link", { name: /github/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /my-tool/ })).not.toBeVisible();
  });

  test("source filter narrows to custom skills", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await page.getByRole("menuitemradio", { name: "Custom" }).click();

    await expect(page.getByRole("link", { name: /my-tool/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /github/ })).not.toBeVisible();
  });

  test("search with no matches shows 'No skills match'", async ({ page }) => {
    await page.getByLabel("Search skills").fill("xyznonexistent");

    await expect(page.getByText("No skills match.")).toBeVisible();
  });

  test("clicking a skill card navigates to its detail page", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillFilesRequest();
    await dataSupportPage.skills.interceptGetSkillVersionsRequest();

    await page.getByRole("link", { name: /my-tool/ }).click();

    await expect(page).toHaveURL(new RegExp(`/settings/skills/${MOCK_CUSTOM_SKILL_ID}$`));
    await expect(page.getByRole("heading", { name: mockCustomSkill.name })).toBeVisible();
  });

  test("clicking New skill navigates to the new-skill page", async ({ page }) => {
    await page.getByRole("link", { name: /new skill/i }).click();

    await expect(page).toHaveURL(new RegExp(`/settings/skills/new$`));
    await expect(page.getByRole("heading", { name: "New skill" })).toBeVisible();
  });
});

test.describe("Settings — Skills panel (empty state)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("shows empty state when no skills exist", async ({ page }) => {
    const dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    // The Settings page opens on the Agents tab.
    await dataSupportPage.organizations.interceptAgentSettings();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({ body: [] });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    // The Settings page opens on the Agents tab.
    await dataSupportPage.organizations.interceptAgentSettings();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({
      status: 500,
      detail: "Skills service unavailable",
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    // The Settings page opens on the Agents tab.
    await dataSupportPage.organizations.interceptAgentSettings();
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

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByRole("button", { name: "Next", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Previous", exact: true })).toBeVisible();
  });

  test("pagination controls are hidden when all results fit on one page", async ({ page }) => {
    await dataSupportPage.skills.interceptGetSkillsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
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

    await page.route("**/api/v1/organizations/*/skills*", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      const url = new URL(route.request().url());
      if (!/\/api\/v1\/organizations\/[^/]+\/skills$/.test(url.pathname)) { await route.fallback(); return; }
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

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
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

    await page.route("**/api/v1/organizations/*/skills*", async (route) => {
      if (route.request().method() !== "GET") { await route.fallback(); return; }
      const url = new URL(route.request().url());
      if (!/\/api\/v1\/organizations\/[^/]+\/skills$/.test(url.pathname)) { await route.fallback(); return; }
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

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
    await page.getByRole("button", { name: "Skills" }).click();

    // Advance to page 2.
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByText("2 / 2")).toBeVisible();

    // Typing in search should reset back to page 1.
    await page.getByLabel("Search skills").fill("skill-0");
    await expect(page.getByRole("button", { name: "Next", exact: true })).not.toBeVisible();
  });
});
