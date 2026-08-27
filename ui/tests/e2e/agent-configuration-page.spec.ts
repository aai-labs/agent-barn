import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  MOCK_CUSTOM_SKILL_ID,
  mockCustomSkill,
} from "../pages/data-support/skill-data-support.po";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentConfiguration,
  mockAgentOverrideDraft,
  mockAgentOverrideVersion,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Agent configuration page", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("shows a useful alert when the Agent is in an error state", async ({ page }) => {
    const dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "ERROR" },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: {
        status: "error",
        reason: "The runtime could not load the selected configuration.",
      },
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration`);

    const alert = page.locator('[data-slot="alert"]');
    await expect(alert).toContainText("Agent needs attention");
    await expect(alert).toContainText("could not load the selected configuration");
    await expect(alert.getByRole("link", { name: "View Agent logs" })).toBeVisible();
  });

  test("keeps the selected tab in the URL and restores it on refresh", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({ body: mockAgent });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetTemplateVersionsRequest();

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await expect(configurationPage.profileHeading()).toBeVisible();

    await configurationPage.sectionButton("Agent-owned override").click();
    await expect(page).toHaveURL(/section=override/);

    await page.reload();
    await expect(page.getByRole("heading", { name: "No active override" })).toBeVisible();
    await expect(page).toHaveURL(/section=override/);
  });

  test("creates, saves, publishes, and selects an Agent-owned override", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    let currentAgent: Record<string, unknown> = { ...mockAgent, status: "STOPPED" };
    let draft = { ...mockAgentOverrideDraft };
    let configuration: Record<string, unknown> = {
      ...mockAgentConfiguration,
      active: { ...mockAgentConfiguration.active },
      shared_versions: [mockAgentConfiguration.active],
      override_versions: [],
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.skills.interceptGetSkillsRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetTemplateVersionsRequest();

    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentAgent) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(configuration) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/draft`, async (route) => {
      if (route.request().method() === "POST") {
        configuration = { ...configuration, draft };
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(draft) });
        return;
      }
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        draft = {
          ...draft,
          soul_md: (body.soul_md as string | undefined) ?? draft.soul_md,
          template_name: (body.template_name as string | undefined) ?? draft.template_name,
          updated_at: "2026-05-14T09:16:00Z",
        };
        configuration = { ...configuration, draft };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(draft) });
        return;
      }
      await route.fallback();
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/draft/publish`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      configuration = { ...configuration, draft: null, override_versions: [mockAgentOverrideVersion] };
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(mockAgentOverrideVersion) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/select`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      const body = route.request().postDataJSON() as Record<string, unknown>;
      expect(body.selection_type).toBe("override");
      expect(body.override_version).toBe(1);
      expect(body.template_key).toBeUndefined();
      expect(body.template_version).toBeUndefined();
      currentAgent = { ...currentAgent, template_pin_type: "override", override_version: 1 };
      configuration = {
        ...configuration,
        active: { ...mockAgentOverrideVersion, state: "active" },
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentAgent) });
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(configurationPage.profileHeading()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Runtime & deployment" })).toBeVisible();

    await configurationPage.sectionButton("Agent-owned override").click();
    await expect(page.getByRole("heading", { name: "No active override" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
    await configurationPage.startDraftButton().click();
    await expect(configurationPage.draftHeading()).toBeVisible();

    await configurationPage.artifact("SOUL.md").last().fill("# Agent-specific soul");
    await expect(configurationPage.saveDraftButton()).toBeEnabled();
    await configurationPage.saveDraftButton().click();
    await expect(page.getByRole("heading", { name: "Override draft" })).toBeVisible();
    await expect(configurationPage.saveDraftButton()).toHaveCount(0);

    await configurationPage.publishButton().click();
    await expect(configurationPage.publishConfirmButton()).toBeVisible();
    await configurationPage.publishConfirmButton().click();
    await expect(page.getByRole("heading", { name: "Published override history" })).toBeVisible();
    await expect(page.getByText("A private Agent-owned configuration based on the source template below.")).toBeVisible();
    await expect(page.getByText("Published by")).toBeVisible();
    await expect(page.getByText("Template key").last()).toBeVisible();
    await configurationPage.sectionButton("Template selection").click();
    await configurationPage.versionSelect().click();
    await page.getByRole("option", { name: /Maya.*v1.*Agent override/i }).click();
    await configurationPage.applyButton().click();
    await expect(configurationPage.applyConfirmationButton()).toBeVisible();
    await configurationPage.applyConfirmationButton().click();
    await expect(configurationPage.applyButton()).toBeDisabled();
    await configurationPage.sectionButton("Agent-owned override").click();
    await expect(page.getByRole("heading", { name: "No override draft" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create new draft" })).toBeVisible();
  });

  test("edits an existing Override Draft loaded from the server", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    let draft = { ...mockAgentOverrideDraft, updated_at: "2026-05-14T09:14:00Z" };
    const configuration = {
      ...mockAgentConfiguration,
      draft,
      shared_versions: [mockAgentConfiguration.active],
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await dataSupport.skills.interceptGetSkillsRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(configuration) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/draft`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      const body = route.request().postDataJSON() as Record<string, unknown>;
      draft = { ...draft, soul_md: (body.soul_md as string | undefined) ?? draft.soul_md, updated_at: "2026-05-14T09:16:00Z" };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(draft) });
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Agent-owned override").click();

    await expect(page.getByRole("heading", { name: "Override draft" })).toBeVisible();
    await page.getByRole("button", { name: "Edit", exact: true }).click();

    await expect(configurationPage.draftHeading()).toBeVisible();
    const soulField = configurationPage.artifact("SOUL.md").last();
    await soulField.fill("# Edited existing draft");
    await expect(soulField).toHaveValue("# Edited existing draft");
    await expect(configurationPage.saveDraftButton()).toBeEnabled();

    await configurationPage.saveDraftButton().click();
    await expect(page.getByRole("heading", { name: "Override draft" })).toBeVisible();
    await expect(configurationPage.saveDraftButton()).toHaveCount(0);
  });

  test("repins to a labeled Platform source update without changing the local Override Draft", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const sourceUpdate = {
      ...mockAgentConfiguration.active,
      id: "66666666-6666-4666-8666-666666666662",
      version: 2,
      template_name: "General Purpose",
      description: "Platform source v2",
      soul_md: "# Platform source v2",
      source_type: "platform",
      source_template_key: "general-purpose",
      source_template_version: 2,
      source_platform_template_id: "55555555-5555-4555-8555-555555555551",
      source_agent_template_id: null,
      state: "published",
      pin_type: "shared",
    };
    const localDraft = {
      ...mockAgentOverrideDraft,
      soul_md: "# Local draft change",
    };
    let configuration: Record<string, unknown> = {
      ...mockAgentConfiguration,
      active: { ...mockAgentOverrideVersion, state: "active" },
      draft: localDraft,
      override_versions: [mockAgentOverrideVersion],
      source_update: sourceUpdate,
    };
    let currentAgent: Record<string, unknown> = {
      ...mockAgent,
      status: "STOPPED",
      template_pin_type: "override",
      override_version: 1,
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.skills.interceptGetSkillsRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetTemplateVersionsRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentAgent) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(configuration) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/select`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      currentAgent = { ...currentAgent, template_pin_type: "shared", override_version: null };
      configuration = {
        ...configuration,
        active: { ...sourceUpdate, state: "active" },
        source_update: null,
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentAgent) });
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Template selection").click();
    await expect(page.getByText(/newer Platform source version \(v2\)/)).toBeVisible();
    await configurationPage.versionSelect().click();
    await expect(page.getByText("Platform update").first()).toBeVisible();
    await page.getByRole("option", { name: /v2.*Platform update/i }).click();
    await configurationPage.applyButton().click();
    await configurationPage.applyConfirmationButton().click();
    await expect(configurationPage.applyButton()).toBeDisabled();

    await configurationPage.sectionButton("Agent-owned override").click();
    await expect(configurationPage.draftHeading()).toBeVisible();
    await expect(configurationPage.artifact("SOUL.md").last()).toHaveValue("# Local draft change");
  });

  test("restarts a running Agent even when a source-update selection fails", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const sourceUpdate = {
      ...mockAgentConfiguration.active,
      id: "66666666-6666-4666-8666-666666666662",
      version: 2,
      template_name: "Maya Organization",
      source_template_version: 2,
      state: "published",
      pin_type: "shared",
    };
    const configuration = {
      ...mockAgentConfiguration,
      active: { ...mockAgentOverrideVersion, state: "active" },
      source_update: sourceUpdate,
      override_versions: [mockAgentOverrideVersion],
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.skills.interceptGetSkillsRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetTemplateVersionsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING", template_pin_type: "override", override_version: 1 },
    });
    await dataSupport.agents.interceptStopAgentRequest();
    await dataSupport.agents.interceptStartAgentRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(configuration) });
    });
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/configuration/select`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "Selection conflict" }) });
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Template selection").click();
    await configurationPage.versionSelect().click();
    await page.getByRole("option", { name: /v2.*Organization update/i }).click();
    await configurationPage.applyButton().click();
    const stopPromise = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/stop`) && request.method() === "POST",
    );
    const startPromise = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/start`) && request.method() === "POST",
    );
    await configurationPage.applyConfirmationButton().click();
    await Promise.all([stopPromise, startPromise]);
  });

  test("keeps override creation available and restarts running Agents when applying changes", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING" },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetModelsRequest();
    await dataSupport.agents.interceptUpdateAgentRequest();
    await dataSupport.agents.interceptStopAgentRequest();
    await dataSupport.agents.interceptStartAgentRequest();

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Agent-owned override").click();
    await expect(page.getByRole("button", { name: "Create override", exact: true })).toBeVisible();

    await configurationPage.sectionButton("Profile").click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Agent name").fill("Maya running");

    const stopPromise = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/stop`) && request.method() === "POST",
    );
    const updatePromise = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}`) && request.method() === "PATCH",
    );
    const startPromise = page.waitForRequest(
      (request) => request.url().endsWith(`/agents/${MOCK_AGENT_ID}/start`) && request.method() === "POST",
    );

    const footer = page.locator('section[aria-label="Profile"] footer');
    await expect(footer.getByRole("button", { name: "Apply & Restart", exact: true })).toBeEnabled();
    await footer.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();

    await Promise.all([stopPromise, updatePromise, startPromise]);
  });

  test("keeps the Skills editor visible and enables Apply for a pending addition", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [] },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Skills").click();

    const section = page.locator('section[aria-label="Skills"]');
    await expect(section.getByPlaceholder("Search skills…")).toBeVisible();
    await expect(section.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);

    const applyButton = section.getByRole("button", { name: "Apply", exact: true });
    await expect(applyButton).toBeDisabled();

    // my-tool is the second fixture row and has no credential requirements.
    await section.getByRole("button", { name: "Add", exact: true }).nth(1).click();
    await expect(section.getByText("my-tool", { exact: true }).last()).toBeVisible();
    await expect(applyButton).toBeEnabled();
  });

  test("enables Apply when an assigned skill is marked for removal", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const assignedSkill = {
      id: MOCK_CUSTOM_SKILL_ID,
      name: "my-tool",
      source: "custom",
      requiredProviders: [],
      toolsPointer: null,
      required: false,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
      version: 1,
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [assignedSkill] },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Skills").click();

    const section = page.locator('section[aria-label="Skills"]');
    const applyButton = section.getByRole("button", { name: "Apply", exact: true });
    await expect(applyButton).toBeDisabled();
    await section.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(section.getByRole("button", { name: "Undo", exact: true })).toBeVisible();
    await expect(applyButton).toBeEnabled();
  });

  test("loads more available skills as the user reaches the end of the list", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const firstPage = Array.from({ length: 15 }, (_, index) => ({
      ...mockCustomSkill,
      id: `66666666-6666-4666-8666-${String(index).padStart(12, "0")}`,
      name: `paged-skill-${index}`,
      slug: `paged-skill-${index}`,
    }));
    const secondPage = {
      ...mockCustomSkill,
      id: "66666666-6666-4666-8666-000000000015",
      name: "paged-skill-15",
      slug: "paged-skill-15",
    };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [] },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest({
      pages: [firstPage, [secondPage]],
      total: 16,
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Skills").click();
    await expect(page.getByText("paged-skill-0", { exact: true })).toBeVisible();

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText("paged-skill-15", { exact: true })).toBeVisible();
  });

  test("debounces Skills search and sends the query to the API", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const skillRequests: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        request.method() === "GET" &&
        url.pathname.endsWith(`/agents/${MOCK_AGENT_ID}/skills`)
      ) {
        skillRequests.push(url.toString());
      }
    });

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [] },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Skills").click();
    const search = page.getByPlaceholder("Search skills…");
    await expect(search).toBeVisible();
    await expect.poll(() => skillRequests.length).toBe(1);

    await search.fill("jira");
    await expect.poll(() => skillRequests.length, { timeout: 200 }).toBe(1);
    await expect.poll(() => skillRequests.length, { timeout: 2_000 }).toBe(2);
    expect(new URL(skillRequests[1]).searchParams.get("search")).toBe("jira");
  });

  test("re-pins an assigned skill to a specific version and sends skill_versions", async ({ page }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);
    const assignedSkill = {
      id: MOCK_CUSTOM_SKILL_ID,
      name: "my-tool",
      source: "custom",
      requiredProviders: [],
      toolsPointer: null,
      required: false,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
      version: 1,
    };
    let currentAgent = { ...mockAgent, status: "STOPPED", skills: [assignedSkill] };

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({ body: currentAgent });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.skills.interceptGetSkillsRequest();
    await dataSupport.skills.interceptGetAgentSkillsRequest();
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/skills/${MOCK_CUSTOM_SKILL_ID}/versions`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { version: 2, created_by: null, created_at: "2026-01-02T00:00:00Z", is_pinned_by_agent: false },
          { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z", is_pinned_by_agent: false },
        ]),
      });
    });
    let sentBody: Record<string, unknown> | undefined;
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      sentBody = route.request().postDataJSON() as Record<string, unknown>;
      currentAgent = { ...currentAgent, skills: [{ ...assignedSkill, version: 2 }] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentAgent) });
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Skills").click();
    await expect(page.getByRole("combobox", { name: "Version for my-tool" })).toHaveText("Version v1");
    await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);

    await page.getByRole("combobox", { name: "Version for my-tool" }).click();
    await page.getByRole("option", { name: "Version v2", exact: true }).click();

    const footer = page.locator('section[aria-label="Skills"] footer');
    await expect(footer.getByRole("button", { name: "Apply", exact: true })).toBeEnabled();
    await footer.getByRole("button", { name: "Apply", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply", exact: true }).click();

    expect(sentBody?.skill_versions).toEqual([{ skill_id: MOCK_CUSTOM_SKILL_ID, version: 2 }]);
    await expect(page.getByText("v2")).toBeVisible();
  });
});
