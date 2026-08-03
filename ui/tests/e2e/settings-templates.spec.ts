import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import {
  mockAgentTemplate,
  mockAssignedSkill,
  mockTemplates,
  mockVersionsForSlug,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  MOCK_BITBUCKET_SKILL_ID,
  MOCK_JIRA_SKILL_ID,
  MOCK_PLATFORM_SKILL_ID,
  mockBitbucketSkill,
  mockJiraSkill,
  mockPlatformSkill,
} from "../pages/data-support/skill-data-support.po";

test.describe("Settings · Templates", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetTemplateVersionsRequest();
    await dataSupport.skills.interceptGetSkillsRequest();

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
    await page.getByRole("button", { name: "Templates", exact: true }).click();
  });

  test("lists templates with slug, version, and source badges", async ({ page }) => {
    await expect(page.getByText("General Purpose", { exact: true })).toBeVisible();
    await expect(page.getByText("· general-purpose@v1")).toBeVisible();
    // Badge spans only — the source filter <option> also says "Pre-defined".
    await expect(page.locator('span:text-is("Pre-defined")')).toHaveCount(2);
    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
  });

  test("search filters the list", async ({ page }) => {
    await page.getByLabel("Search templates").fill("scrum");

    await expect(page.getByText("Scrum Master", { exact: true })).toBeVisible();
    await expect(page.getByText("General Purpose", { exact: true })).not.toBeVisible();
  });

  test("source filter narrows to custom templates", async ({ page }) => {
    await page.getByLabel("Filter by source").click();
    await page.getByRole("menuitemradio", { name: "Custom" }).click();

    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
    await expect(page.getByText("Scrum Master", { exact: true })).not.toBeVisible();
  });

  test("clicking a template opens a read-only preview with a version dropdown", async ({ page }) => {
    await page.getByText("Scrum Master", { exact: true }).click();

    await expect(page.getByRole("heading", { name: "Scrum Master" })).toBeVisible();
    // Version dropdown defaults to latest (v2).
    const version = page.getByLabel("Version");
    await expect(version).toContainText("v2");
    const content = page.getByLabel("SOUL.md content");
    await expect(content).toHaveAttribute("readonly", "");
    await expect(content).toHaveValue(/# Soul v2/);
    await expect(content).toHaveValue(/\{\{ agent_display_name \}\}/);

    // Switching the version changes the displayed content.
    await version.click();
    await page.getByRole("menuitemradio", { name: "v1" }).click();
    await expect(content).toHaveValue(/# Soul v1/);

    // The name is shown but not editable in view mode.
    await expect(page.getByLabel("Template name")).toHaveCount(0);
  });

  test("edit template enables fields and save publishes a new version (name inherited)", async ({ page }) => {
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    const content = page.getByLabel("SOUL.md content");
    await expect(content).not.toHaveAttribute("readonly", "");
    await content.fill("# Soul next");

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    expect(body.soul_md).toBe("# Soul next");
    // Name is immutable — never sent on update.
    expect(body.template_name).toBeUndefined();

    await expect(page.getByText("Saved as v2")).toBeVisible();
  });

  test("new template posts template_name and md content", async ({ page }) => {
    await dataSupport.agents.interceptCreateTemplateRequest({
      body: { ...mockAgentTemplate, template_slug: "support-helper", template_name: "Support Helper" },
    });

    await page.getByRole("button", { name: /new template/i }).click();
    await page.getByLabel("Template name").fill("Support Helper");
    await expect(page.getByText("Slug:")).toContainText("support-helper");
    await page.getByLabel("SOUL.md content").fill("# A fresh soul");

    const createPromise = page.waitForRequest(
      (req) =>
        /\/api\/v1\/organizations\/[^/]+\/templates$/.test(new URL(req.url()).pathname) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Create template" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as Record<string, unknown>;
    expect(body.template_name).toBe("Support Helper");
    expect(body.soul_md).toBe("# A fresh soul");
  });

  test("conflict on create surfaces the backend error", async ({ page }) => {
    await dataSupport.agents.interceptCreateTemplateRequest({
      status: 409,
      detail: `A template with slug ${mockTemplates[2].template_slug} already exists`,
    });

    await page.getByRole("button", { name: /new template/i }).click();
    await page.getByLabel("Template name").fill("My Custom");
    await page.getByRole("button", { name: "Create template" }).click();

    await expect(page.getByText(/already exists/)).toBeVisible();
  });

  test("view mode shows Required skills None when template has no required skills", async ({ page }) => {
    await page.getByText("My Custom", { exact: true }).click();

    await expect(page.getByText("Required skills")).toBeVisible();
    await expect(page.getByText("None", { exact: true })).toBeVisible();
  });

  test("view mode shows required skill pill when template has required skills", async ({ page }) => {
    const versions = mockVersionsForSlug("my-custom").map((v) => ({
      ...v,
      required_skills: [mockAssignedSkill],
    }));
    await dataSupport.agents.interceptGetTemplateVersionsRequest({ body: versions });

    await page.getByText("My Custom", { exact: true }).click();

    await expect(page.getByText("Required skills")).toBeVisible();
    await expect(page.getByText(mockAssignedSkill.name, { exact: true })).toBeVisible();
  });

  test("edit mode adding a skill sends required_skill_ids in PATCH body", async ({ page }) => {
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    // Add the first available skill (github).
    await page.getByRole("button", { name: "Add" }).first().click();

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    expect(body.required_skill_ids).toEqual([MOCK_PLATFORM_SKILL_ID]);
  });

  test("grouping action is hidden until at least two skills are selected", async ({ page }) => {
    await dataSupport.skills.interceptGetSkillsRequest({ body: [mockPlatformSkill, mockBitbucketSkill] });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();
    await page.getByRole("button", { name: "Group skills" }).click();

    await expect(page.getByRole("button", { name: /Group as/ })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Select", exact: true }).first().click();
    await expect(page.getByRole("button", { name: /Group as/ })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Select", exact: true }).first().click();
    await expect(page.getByRole("button", { name: /Group as/ })).toBeVisible();
  });

  test("creating a group from two selected skills sends required_skill_groups in PATCH body", async ({ page }) => {
    await dataSupport.skills.interceptGetSkillsRequest({ body: [mockPlatformSkill, mockBitbucketSkill] });
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();
    await page.getByRole("button", { name: "Group skills" }).click();

    const selectCheckbox = page.getByRole("checkbox", { name: "Select", exact: true });
    await selectCheckbox.first().click();
    await selectCheckbox.first().click();
    await page.getByRole("button", { name: /Group as/ }).click();

    await expect(page.getByTestId("required-skill-group-bitbucket-or-github")).toBeVisible();

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    const groups = body.required_skill_groups as { group_key: string; skill_ids: string[] }[];
    expect(groups).toHaveLength(1);
    expect([...groups[0].skill_ids].sort()).toEqual(
      [MOCK_PLATFORM_SKILL_ID, MOCK_BITBUCKET_SKILL_ID].sort(),
    );
    expect(groups[0].group_key.length).toBeGreaterThan(0);
    expect(groups[0].group_key.length).toBeLessThanOrEqual(100);
    expect(body.required_skill_ids).toEqual([]);
  });

  test("adding a member to an existing group sends the expanded member list, preserving group_key", async ({ page }) => {
    const base = { ...mockAssignedSkill, group_key: "vcs-group" };
    const githubReq = { ...base, id: MOCK_PLATFORM_SKILL_ID, name: "github", required_providers: ["github"] };
    const bitbucketReq = { ...base, id: MOCK_BITBUCKET_SKILL_ID, name: "bitbucket", required_providers: ["bitbucket"] };
    const versions = mockVersionsForSlug("my-custom").map((v) => ({
      ...v,
      required_skills: [githubReq, bitbucketReq],
    }));
    await dataSupport.agents.interceptGetTemplateVersionsRequest({ body: versions });
    await dataSupport.skills.interceptGetSkillsRequest({
      body: [mockPlatformSkill, mockBitbucketSkill, mockJiraSkill],
    });
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    const groupCard = page.getByTestId("required-skill-group-vcs-group");
    await expect(groupCard).toBeVisible();
    await groupCard.getByRole("button", { name: "Add" }).click();

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    const groups = body.required_skill_groups as { group_key: string; skill_ids: string[] }[];
    expect(groups).toHaveLength(1);
    expect(groups[0].group_key).toBe("vcs-group");
    expect([...groups[0].skill_ids].sort()).toEqual(
      [MOCK_PLATFORM_SKILL_ID, MOCK_BITBUCKET_SKILL_ID, MOCK_JIRA_SKILL_ID].sort(),
    );
  });

  test("removing a group member down to 2 keeps the group; down to 0 removes it", async ({ page }) => {
    const base = { ...mockAssignedSkill, group_key: "vcs-group" };
    const githubReq = { ...base, id: MOCK_PLATFORM_SKILL_ID, name: "github", required_providers: ["github"] };
    const bitbucketReq = { ...base, id: MOCK_BITBUCKET_SKILL_ID, name: "bitbucket", required_providers: ["bitbucket"] };
    const jiraReq = { ...base, id: MOCK_JIRA_SKILL_ID, name: "jira", required_providers: ["jira"] };
    const versions = mockVersionsForSlug("my-custom").map((v) => ({
      ...v,
      required_skills: [githubReq, bitbucketReq, jiraReq],
    }));
    await dataSupport.agents.interceptGetTemplateVersionsRequest({ body: versions });
    await dataSupport.skills.interceptGetSkillsRequest({
      body: [mockPlatformSkill, mockBitbucketSkill, mockJiraSkill],
    });
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    const groupCard = page.getByTestId("required-skill-group-vcs-group");
    await expect(groupCard).toBeVisible();

    await groupCard.getByRole("button", { name: "Remove" }).first().click();
    await expect(groupCard).toBeVisible();
    await groupCard.getByRole("button", { name: "Remove" }).first().click();
    await expect(groupCard).toBeVisible();
    await groupCard.getByRole("button", { name: "Remove" }).first().click();
    await expect(page.getByTestId("required-skill-group-vcs-group")).toHaveCount(0);

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    expect(body.required_skill_groups).toEqual([]);
    expect(body.required_skill_ids).toEqual([]);
  });

  test("dissolving a group folds members into standalone and sends required_skill_ids instead", async ({ page }) => {
    const base = { ...mockAssignedSkill, group_key: "vcs-group" };
    const githubReq = { ...base, id: MOCK_PLATFORM_SKILL_ID, name: "github", required_providers: ["github"] };
    const bitbucketReq = { ...base, id: MOCK_BITBUCKET_SKILL_ID, name: "bitbucket", required_providers: ["bitbucket"] };
    const versions = mockVersionsForSlug("my-custom").map((v) => ({
      ...v,
      required_skills: [githubReq, bitbucketReq],
    }));
    await dataSupport.agents.interceptGetTemplateVersionsRequest({ body: versions });
    await dataSupport.skills.interceptGetSkillsRequest({ body: [mockPlatformSkill, mockBitbucketSkill] });
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    await page.getByRole("button", { name: "Dissolve group" }).click();
    await expect(page.getByTestId("required-skill-group-vcs-group")).toHaveCount(0);

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    expect(body.required_skill_groups).toEqual([]);
    expect([...(body.required_skill_ids as string[])].sort()).toEqual(
      [MOCK_PLATFORM_SKILL_ID, MOCK_BITBUCKET_SKILL_ID].sort(),
    );
  });
});
