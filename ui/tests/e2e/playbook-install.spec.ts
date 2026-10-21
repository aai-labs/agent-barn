import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { MOCK_ORG_TEMPLATE_KEY, mockOrgTemplateDraft } from "../pages/data-support/org-template-data-support.po";
import { mockSucceededRun } from "../pages/data-support/playbook-data-support.po";
import { MOCK_CUSTOM_SKILL_ID, mockCustomSkill } from "../pages/data-support/skill-data-support.po";

test.use({ storageState: { cookies: [], origins: [] } });

const VERSION = 2;
// The fixtures' Organization Template Skill ID is the custom Skill's ID, so use one of our own.
const EXISTING_REQUIRED_SKILL_ID = "cccccccc-0000-4000-8000-0000000000c0";

function required(id: string, name: string, groupKey: string | null) {
  return {
    id,
    organization_id: TEST_ORG_ID,
    name,
    source: "custom",
    required_providers: [],
    tools_pointer: null,
    version: 1,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    group_key: groupKey,
  };
}

function assigned(version: number) {
  return {
    id: MOCK_CUSTOM_SKILL_ID,
    name: "Refunds playbook",
    source: "custom",
    scope: "organization",
    required_providers: [],
    tools_pointer: null,
    required: false,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    version,
  };
}

const AGENTS = [
  { ...mockAgent, id: "aaaaaaaa-0000-4000-8000-000000000001", name: "Ada", skills: [], allowed_actions: mockAgentAllowedActions },
  { ...mockAgent, id: "aaaaaaaa-0000-4000-8000-000000000002", name: "Ben", skills: [assigned(1)], allowed_actions: mockAgentAllowedActions },
  { ...mockAgent, id: "aaaaaaaa-0000-4000-8000-000000000003", name: "Cy", skills: [assigned(VERSION)], allowed_actions: mockAgentAllowedActions },
  { ...mockAgent, id: "aaaaaaaa-0000-4000-8000-000000000004", name: "Dee", skills: [], allowed_actions: ["agent.read"] },
];

async function openPublishedPlaybook(page: Page, { version = VERSION }: { version?: number | null } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.skills.interceptGetSkillFilesRequest({
    skill: { ...mockCustomSkill, name: "Refunds playbook", version },
    files: [{ path: "SKILL.md", content: "# Refunds playbook" }],
  });
  await data.skills.interceptGetSkillVersionsRequest();
  await data.playbooks.intercept({ runs: [mockSucceededRun({ skill_id: MOCK_CUSTOM_SKILL_ID })] });
  await data.agents.interceptGetAgentsRequest({
    body: { page: 1, page_size: 50, total: AGENTS.length, items: AGENTS },
  });
  await page.goto(`/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_CUSTOM_SKILL_ID}`);
  return data;
}

test("a published playbook is added to chosen Agents, moving older pins forward", async ({ page }) => {
  await openPublishedPlaybook(page);
  const patches: Record<string, unknown> = {};
  await page.route("**/api/v1/organizations/*/agents/aaaaaaaa-*", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    const agentId = new URL(route.request().url()).pathname.split("/").at(-1)!;
    patches[agentId] = route.request().postDataJSON();
    if (agentId.endsWith("2")) {
      return route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Ben is missing a credential this Skill needs." }),
      });
    }
    const agent = AGENTS.find((item) => item.id === agentId)!;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...agent, skills: [assigned(VERSION)] }) });
  });

  await page.getByRole("button", { name: "Add to Agents" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("checkbox", { name: "Cy" })).toBeDisabled();
  await expect(dialog.getByRole("checkbox", { name: "Dee" })).toHaveCount(0);
  await expect(dialog).toContainText("Has version 1");
  await dialog.getByRole("checkbox", { name: "Ada" }).click();
  await dialog.getByRole("checkbox", { name: "Ben" }).click();
  await dialog.getByRole("button", { name: "Add to 2 Agents" }).click();

  await expect(dialog.getByRole("list", { name: "Results" })).toContainText("Ada: now on version 2");
  await expect(dialog.getByRole("list", { name: "Results" })).toContainText(
    "Ben: Ben is missing a credential this Skill needs.",
  );
  await expect(dialog).toContainText("Running Agents load the playbook the next time they restart.");
  expect(patches).toEqual({
    [AGENTS[0].id]: {
      skill_ids: [MOCK_CUSTOM_SKILL_ID],
      skill_versions: [{ skill_id: MOCK_CUSTOM_SKILL_ID, version: VERSION }],
    },
    [AGENTS[1].id]: { skill_versions: [{ skill_id: MOCK_CUSTOM_SKILL_ID, version: VERSION }] },
  });
});

test("a published playbook is added to a Template's draft, keeping its other requirements", async ({ page }) => {
  const data = await openPublishedPlaybook(page);
  await data.orgTemplates.interceptGetLineages();
  const existing = required(EXISTING_REQUIRED_SKILL_ID, "Existing", null);
  const grouped = required("cccccccc-0000-4000-8000-0000000000c1", "Grouped", "crm");
  await data.orgTemplates.interceptStartDraft({
    body: { ...mockOrgTemplateDraft, required_skills: [existing, grouped] },
  });
  const update = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().endsWith(`/templates/${MOCK_ORG_TEMPLATE_KEY}/draft`),
  );
  await data.orgTemplates.interceptUpdateDraft();

  await page.getByRole("button", { name: "Require on a Template" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Template" }).click();
  await page.getByRole("option", { name: "My Custom" }).click();
  await dialog.getByRole("button", { name: "Add to draft" }).click();

  expect((await update).postDataJSON()).toEqual({
    required_skill_ids: [EXISTING_REQUIRED_SKILL_ID, MOCK_CUSTOM_SKILL_ID],
    required_skill_versions: { [MOCK_CUSTOM_SKILL_ID]: VERSION },
  });
  await expect(dialog.getByRole("status")).toContainText("Added to the draft of My Custom");
  await expect(dialog.getByRole("link", { name: "Open Template" })).toHaveAttribute(
    "href",
    `/dashboard/${TEST_ORG_ID}/settings/templates/${MOCK_ORG_TEMPLATE_KEY}`,
  );
});

test("a Template that already requires the playbook is left unchanged", async ({ page }) => {
  const data = await openPublishedPlaybook(page);
  await data.orgTemplates.interceptGetLineages();
  await data.orgTemplates.interceptStartDraft({
    body: { ...mockOrgTemplateDraft, required_skills: [required(MOCK_CUSTOM_SKILL_ID, "Refunds playbook", null)] },
  });
  let patched = false;
  await page.route(`**/templates/${MOCK_ORG_TEMPLATE_KEY}/draft`, (route) => {
    if (route.request().method() === "PATCH") patched = true;
    return route.fallback();
  });

  await page.getByRole("button", { name: "Require on a Template" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Template" }).click();
  await page.getByRole("option", { name: "My Custom" }).click();
  await dialog.getByRole("button", { name: "Add to draft" }).click();

  await expect(dialog.getByRole("status")).toContainText("already requires this playbook");
  expect(patched).toBe(false);
});

test("a playbook that was never published offers no install actions", async ({ page }) => {
  await openPublishedPlaybook(page, { version: null });

  await expect(page.getByRole("region", { name: "Playbook source" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add to Agents" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Require on a Template" })).toHaveCount(0);
});
