import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  mockPlatformTemplateDraft,
  mockPlatformTemplatePublished,
  mockPlatformTemplatePublishedV1,
} from "../pages/data-support/platform-template-data-support.po";

test.describe("Platform Template Admin", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("lists platform templates and saves an existing draft", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformTemplates.interceptGetLineages();
    await data.platformTemplates.interceptGetVersions();
    await data.platformTemplates.interceptGetDraft();
    await data.platformTemplates.interceptGetGlobalSkills({
      body: [
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          organization_id: null,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    await data.platformTemplates.interceptUpdateDraft();

    await page.goto("/dashboard/platform/templates");

    await expect(page.getByRole("heading", { name: /platform templates/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /code reviewer/i })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /code reviewer/i }).click();
    await expect(page).toHaveURL(/\/dashboard\/platform\/templates\/code-reviewer$/);
    await expect(page.getByRole("heading", { name: "Code Reviewer" })).toBeVisible();
    await expect(page.getByText("Current", { exact: true })).toBeVisible();
    await expect(page.getByLabel("SOUL.md content")).toHaveText(/careful code reviewer/);
    await expect(page.getByRole("tab", { name: "SOUL.md", exact: true })).toHaveAttribute("data-state", "active");
    await page.getByRole("tab", { name: "IDENTITY.md", exact: true }).click();
    await expect(page.getByLabel("IDENTITY.md content")).toHaveText(/# Identity/);
    await page.getByRole("tab", { name: "SOUL.md", exact: true }).click();
    await expect(page.getByLabel("Published version")).toHaveValue("2");
    await expect(page.getByLabel("Published version").locator("option:checked")).toHaveText("Version v2");
    await page.getByLabel("Published version").selectOption("1");
    await expect(page.getByText("Historical", { exact: true })).toBeVisible();
    await expect(page.getByLabel("SOUL.md content")).toHaveText(/version one/);
    await page.getByLabel("Published version").selectOption("2");
    await expect(page.getByText("Current", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /continue editing draft/i }).click();
    await expect(page.getByRole("button", { name: /view published version/i })).toBeVisible();
    await page.getByRole("button", { name: /view published version/i }).click();
    await expect(page.getByText("Current", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /continue editing draft/i })).toBeVisible();

    await page.getByRole("button", { name: /continue editing draft/i }).click();
    await expect(page.getByRole("tab", { name: "SOUL.md", exact: true })).toHaveAttribute("data-state", "active");
    await page.getByRole("tab", { name: "IDENTITY.md", exact: true }).click();
    await expect(page.getByLabel("IDENTITY.md content")).toHaveValue(/# Identity/);
    await page.getByRole("tab", { name: "SOUL.md", exact: true }).click();
    await expect(page.getByLabel("SOUL.md content")).toHaveValue(/careful code reviewer/);

    await page.getByLabel("Description").fill("Updated from the Platform Admin UI.");
    await page.getByRole("button", { name: /save draft/i }).click();
    await expect(page.getByText("Draft saved.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Platform templates" }).click();
    await expect(page).toHaveURL(/\/dashboard\/platform\/templates$/);
    await page.getByRole("button", { name: "New template" }).click();
    await expect(page).toHaveURL(/\/dashboard\/platform\/templates\/new$/);
    await expect(page.getByRole("heading", { name: "New platform template" })).toBeVisible();
    await expect(page.getByLabel("Template name")).toBeVisible();
  });

  test("shows the start-draft action when a lineage has no draft", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformTemplates.interceptGetLineages({
      body: [
        {
          template_key: "general-purpose",
          template_name: "General Purpose",
          latest_published_version: 1,
          has_draft: false,
        },
      ],
    });
    await data.platformTemplates.interceptGetVersions({
      templateKey: "general-purpose",
      body: [
        {
        ...mockPlatformTemplatePublished,
        template_key: "general-purpose",
        template_name: "General Purpose",
        version: 2,
        },
        {
          ...mockPlatformTemplatePublishedV1,
          template_key: "general-purpose",
          template_name: "General Purpose",
        },
      ],
    });
    await data.platformTemplates.interceptGetDraft({
      body: {
        ...mockPlatformTemplateDraft,
        template_key: "general-purpose",
        template_name: "General Purpose",
        soul_md: "You are a careful code reviewer from version one.",
      },
    });
    await data.platformTemplates.interceptStartDraft({
      templateKey: "general-purpose",
      body: {
        ...mockPlatformTemplateDraft,
        template_key: "general-purpose",
        template_name: "General Purpose",
        soul_md: "You are a careful code reviewer from version one.",
      },
    });
    await data.platformTemplates.interceptGetGlobalSkills();

    let draftRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/v1/platform/templates/general-purpose/draft")) {
        draftRequestCount += 1;
      }
    });

    await page.goto("/dashboard/platform/templates/general-purpose");

    await expect(page.getByRole("heading", { name: "General Purpose" })).toBeVisible();
    await expect(page.getByText("Current", { exact: true })).toBeVisible();
    await page.getByLabel("Published version").selectOption("1");
    await expect(page.getByText("Historical", { exact: true })).toBeVisible();
    await expect(page.getByLabel("SOUL.md content")).toHaveText(/version one/);
    await expect(page.getByRole("button", { name: "Restore v1 as draft" })).toBeVisible();
    await expect(page.getByText("Loading draft…")).not.toBeVisible();
    expect(draftRequestCount).toBe(0);

    await page.getByRole("button", { name: "Restore v1 as draft" }).click();
    await expect(page.getByRole("tab", { name: "SOUL.md", exact: true })).toHaveAttribute("data-state", "active");
    await expect(page.getByLabel("SOUL.md content")).toHaveValue(/version one/);
  });
});
