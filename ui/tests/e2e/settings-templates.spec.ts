import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  MOCK_ORG_FORK_KEY,
  MOCK_ORG_TEMPLATE_KEY,
  mockOrgTemplateDraft,
  mockOrgTemplateLineages,
  mockOrgTemplatePublished,
  mockOrgTemplatePublishedV1,
} from "../pages/data-support/org-template-data-support.po";

const TEMPLATES_TAB = `/dashboard/${TEST_ORG_ID}/settings`;

test.describe("Settings · Templates", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.organizations.interceptAgentSettings();
    await dataSupport.orgTemplates.interceptGetLineages();
    await dataSupport.orgTemplates.interceptGetOrgSkills();
  });

  async function openTemplatesTab(page: import("@playwright/test").Page) {
    await page.goto(TEMPLATES_TAB);
    await page.getByRole("button", { name: "Templates", exact: true }).click();
  }

  test("lists template lineages with draft and source badges", async ({ page }) => {
    await openTemplatesTab(page);

    await expect(page.getByRole("button", { name: /My Custom/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /General Purpose/ })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();
    await expect(page.getByText("Published v1", { exact: true })).toBeVisible();
    await expect(page.locator('span:text-is("Built-in")')).toHaveCount(1);
  });

  test("clicking a lineage navigates to its own page instead of a drawer", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft({ status: 404 });
    await openTemplatesTab(page);

    await page.getByRole("button", { name: /My Custom/ }).click();

    await expect(page).toHaveURL(
      new RegExp(`/dashboard/${TEST_ORG_ID}/settings/templates/${MOCK_ORG_TEMPLATE_KEY}$`),
    );
    await expect(page.getByRole("heading", { name: "My Custom" })).toBeVisible();
    await expect(page.getByLabel("SOUL.md content")).toHaveText(/in-house helper/);
  });

  test("switches between published versions and marks the current one", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft({ status: 404 });
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await expect(page.getByText("Current", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "Published version" }).click();
    await page.getByRole("option", { name: `v${mockOrgTemplatePublishedV1.version}` }).click();

    await expect(page.getByLabel("SOUL.md content")).toHaveText(/version one/);
    await expect(page.getByText("Historical", { exact: true })).toBeVisible();
  });

  test("starts a draft, edits it, saves, and publishes", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft();
    await dataSupport.orgTemplates.interceptStartDraft();
    await dataSupport.orgTemplates.interceptUpdateDraft();
    await dataSupport.orgTemplates.interceptPublishDraft();
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await page.getByRole("button", { name: /Continue editing draft|Start draft/ }).click();

    const soul = page.getByLabel("SOUL.md content");
    await expect(soul).toBeVisible();
    await soul.fill("# Edited by the org");

    const savePayload = page.waitForRequest(
      (request) =>
        request.method() === "PATCH" &&
        request.url().includes(`/templates/${MOCK_ORG_TEMPLATE_KEY}/draft`),
    );
    await page.getByRole("button", { name: "Save draft" }).click();
    const saved = await savePayload;
    expect(saved.postDataJSON().soul_md).toBe("# Edited by the org");

    await page.getByRole("button", { name: "Publish", exact: true }).click();
    const publishRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().includes(`/templates/${MOCK_ORG_TEMPLATE_KEY}/draft/publish`),
    );
    await page.getByRole("button", { name: "Publish template" }).click();
    await publishRequest;
  });

  test("guards against leaving the editor with unsaved changes", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft();
    await dataSupport.orgTemplates.interceptStartDraft();
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await page.getByRole("button", { name: /Continue editing draft|Start draft/ }).click();
    await page.getByLabel("SOUL.md content").fill("# Unsaved");

    await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeDisabled();

    await page.getByRole("button", { name: "Templates", exact: true }).first().click();
    await expect(page.getByRole("dialog")).toContainText(/Close without saving|unsaved/i);
  });

  test("discards a draft", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft();
    await dataSupport.orgTemplates.interceptStartDraft();
    await dataSupport.orgTemplates.interceptDiscardDraft();
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await page.getByRole("button", { name: /Continue editing draft|Start draft/ }).click();
    await page.getByRole("button", { name: "Discard", exact: true }).click();

    const discardRequest = page.waitForRequest(
      (request) =>
        request.method() === "DELETE" &&
        request.url().includes(`/templates/${MOCK_ORG_TEMPLATE_KEY}/draft`),
    );
    await page.getByRole("button", { name: "Discard draft" }).click();
    await discardRequest;
  });

  test("creates a new template as a draft", async ({ page }) => {
    await dataSupport.orgTemplates.interceptCreateDraft();
    await dataSupport.orgTemplates.interceptGetDraft();
    await dataSupport.orgTemplates.interceptUpdateDraft();
    await openTemplatesTab(page);

    await page.getByRole("button", { name: "New template" }).click();
    await expect(page).toHaveURL(new RegExp(`/dashboard/${TEST_ORG_ID}/settings/templates/new$`));

    await page.getByLabel(/Template name/i).fill("Brand New");
    const createRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith(`/organizations/${TEST_ORG_ID}/templates`),
    );
    await page.getByRole("button", { name: "Save draft" }).click();
    const created = await createRequest;
    expect(created.postDataJSON().template_name).toBe("Brand New");
  });

  test("deletes a custom template lineage", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft({ status: 404 });
    await dataSupport.orgTemplates.interceptDeleteTemplate();
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await page.getByRole("button", { name: "Delete", exact: true }).click();

    const deleteRequest = page.waitForRequest(
      (request) =>
        request.method() === "DELETE" &&
        request.url().endsWith(`/templates/${MOCK_ORG_TEMPLATE_KEY}`),
    );
    await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
    await deleteRequest;
  });

  test("surfaces and applies an available platform template update", async ({ page }) => {
    const forkLineages = [
      {
        ...mockOrgTemplateLineages[0],
        template_key: MOCK_ORG_FORK_KEY,
        is_fork: true,
        platform_update_available: true,
      },
      mockOrgTemplateLineages[1],
    ];
    const fork = {
      ...mockOrgTemplatePublished,
      template_key: MOCK_ORG_FORK_KEY,
      template_name: "General Purpose",
      template_source: "pre-defined",
      forked_from_platform_template_id: "11111111-1111-4111-8111-111111111111",
      fork_baseline_platform_template_id: "22222222-2222-4222-8222-222222222222",
      fork_baseline_platform_version: 2,
      platform_update_available: true,
      version: 1,
    };

    await dataSupport.orgTemplates.interceptGetLineages({ body: forkLineages });
    await dataSupport.orgTemplates.interceptGetVersions({ templateKey: MOCK_ORG_FORK_KEY, body: [fork] });
    await dataSupport.orgTemplates.interceptGetDraft({ templateKey: MOCK_ORG_FORK_KEY, status: 404 });
    await dataSupport.orgTemplates.interceptPlatformUpdate({ templateKey: MOCK_ORG_FORK_KEY, body: fork });

    await openTemplatesTab(page);
    await expect(page.getByTestId(`template-update-available-${MOCK_ORG_FORK_KEY}`)).toBeVisible();
    await expect(page.locator('span:text-is("Org fork")')).toBeVisible();

    await page.getByRole("button", { name: /General Purpose/ }).click();
    await expect(page.getByText(/Platform baseline v2/)).toBeVisible();

    await page.getByRole("button", { name: "Apply platform update" }).click();
    const updateRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().includes(`/templates/${MOCK_ORG_FORK_KEY}/platform-update`),
    );
    await page.getByRole("button", { name: "Apply update" }).click();
    await updateRequest;
  });

  test("shows required skills on a published version", async ({ page }) => {
    const withSkill = {
      ...mockOrgTemplatePublished,
      required_skills: [
        {
          id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          organization_id: TEST_ORG_ID,
          name: "jira",
          source: "custom",
          required_providers: ["jira"],
          tools_pointer: null,
          version: 1,
          group_key: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    };
    await dataSupport.orgTemplates.interceptGetVersions({ body: [withSkill] });
    await dataSupport.orgTemplates.interceptGetDraft({ status: 404 });
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await expect(page.getByText("jira", { exact: false })).toBeVisible();
  });

  test("the editor returns to the Templates settings tab", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft({ status: 404 });
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await page.getByRole("button", { name: "Templates", exact: true }).first().click();

    await expect(page).toHaveURL(new RegExp(`/dashboard/${TEST_ORG_ID}/settings\\?tab=templates$`));
  });

  test("draft-only lineages appear with no published version", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetLineages({
      body: [
        {
          ...mockOrgTemplateLineages[1],
          template_key: "brand-new",
          template_name: "Brand New",
          latest_published_version: null,
          has_draft: true,
        },
      ],
    });
    await openTemplatesTab(page);

    await expect(page.getByRole("button", { name: /Brand New/ })).toBeVisible();
    await expect(page.getByText("Not published", { exact: true })).toBeVisible();
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();
  });

  test("the draft is never shown as a published version", async ({ page }) => {
    await dataSupport.orgTemplates.interceptGetVersions();
    await dataSupport.orgTemplates.interceptGetDraft({
      body: { ...mockOrgTemplateDraft, soul_md: "# Unpublished draft content" },
    });
    await page.goto(`${TEMPLATES_TAB}/templates/${MOCK_ORG_TEMPLATE_KEY}`);

    await expect(page.getByLabel("SOUL.md content")).not.toHaveText(/Unpublished draft content/);
  });
});
