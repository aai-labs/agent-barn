import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { AgentPlaybooksPage } from "../pages/agent-playbooks-page.po";
import { mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  MOCK_PLAYBOOK_SKILL_ID,
  mockPlaybookRun,
  mockSucceededRun,
} from "../pages/data-support/playbook-data-support.po";
import { TEST_ORG_ID } from "../constants";
import { MOCK_ORG_TEMPLATE_KEY } from "../pages/data-support/org-template-data-support.po";

test.use({ storageState: { cookies: [], origins: [] } });

function contextWithRole(role: string) {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({ ...membership, role })),
  };
}

async function open(
  page: Page,
  {
    role = "OWNER",
    runs = [],
    preview,
    startStatus,
  }: { role?: string; runs?: Record<string, unknown>[]; preview?: Record<string, unknown>; startStatus?: number } = {},
) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: contextWithRole(role) });
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({
    body: { ...mockAgent, name: "Sally", allowed_actions: mockAgentAllowedActions },
  });
  await data.agents.interceptGetAgentHealthRequest();
  await data.agents.interceptGetConversationChannelsRequest();
  const mock = await data.playbooks.intercept({ runs, preview, startStatus });
  const playbooks = new AgentPlaybooksPage(page);
  await playbooks.goto();
  return { mock, playbooks };
}

test("an Owner previews what a run reads and starts one for a new playbook", async ({ page }) => {
  const { mock, playbooks } = await open(page);

  await expect(playbooks.preview()).toContainText("Reads 20 conversations (41 messages, 137 tool calls)");
  await expect(playbooks.preview()).toContainText("48.0k input and 10.0k output tokens with gpt-4.1-mini");
  await expect(playbooks.form().getByRole("textbox", { name: "Playbook name" })).toHaveValue("Sally playbook");
  await expect(playbooks.form()).toContainText("Role playbook: how Sally does its job");
  await expect(playbooks.form()).toContainText("Organization conventions: rules every Agent should follow");

  await playbooks.create();

  await expect(playbooks.runs().first()).toContainText("Sally playbook");
  await expect(playbooks.runs().first()).toContainText("Queued");
  const start = mock.requests.find((request) => request.method === "POST");
  expect(start?.body).toEqual({ skill_name: "Sally playbook", window_days: 30, max_sessions: 20 });
  await expect(playbooks.createButton()).toBeDisabled();
  await expect(playbooks.form()).toContainText("A playbook extraction is already running for this Agent.");
});

test("the preview follows the chosen period and session bound", async ({ page }) => {
  const { mock, playbooks } = await open(page);
  await expect(playbooks.preview()).toContainText("Reads 20 conversations");

  await playbooks.choose("Conversations from the last", "90 days");
  await playbooks.choose("Read at most", "50 conversations");

  await expect
    .poll(() =>
      mock.requests
        .filter((request) => request.url.pathname.endsWith("/preview"))
        .map((request) => `${request.url.searchParams.get("window_days")}/${request.url.searchParams.get("max_sessions")}`),
    )
    .toContain("90/50");
});

test("a run cannot start when the period has no conversations", async ({ page }) => {
  const { playbooks } = await open(page, {
    preview: { session_count: 0, message_count: 0, tool_call_count: 0, estimated_input_tokens: 0, estimated_output_tokens: 0 },
  });

  await expect(playbooks.form()).toContainText("There are no conversations in this period.");
  await expect(playbooks.createButton()).toBeDisabled();
});

test("a running run updates to a reviewable draft without reloading", async ({ page }) => {
  const running = mockPlaybookRun({ status: "RUNNING", started_at: "2026-10-13T10:00:01Z" });
  const { mock, playbooks } = await open(page, { runs: [running] });
  await expect(playbooks.runs().first()).toContainText("Running");

  mock.update(String(running.id), mockSucceededRun({ id: running.id }));

  const run = playbooks.runs().first();
  await expect(run).toContainText("Ready to review", { timeout: 10_000 });
  await expect(run).toContainText("20 conversations · 41 messages · 137 tool calls · 3 memories · 65.0k tokens");
  await expect(run.getByRole("group", { name: "Role playbook" })).toContainText("How Sally does its job");
  await expect(run.getByRole("link", { name: "Review playbook" })).toHaveAttribute(
    "href",
    `/dashboard/${TEST_ORG_ID}/settings/skills/${MOCK_PLAYBOOK_SKILL_ID}`,
  );
});

test("an active run can be cancelled after confirmation", async ({ page }) => {
  const queued = mockPlaybookRun();
  const { mock, playbooks } = await open(page, { runs: [queued] });

  await playbooks.cancelRun(playbooks.runs().first());

  await expect(playbooks.runs().first()).toContainText("Cancelled");
  expect(mock.requests.some((request) => request.url.pathname.endsWith(`/${queued.id}/cancel`))).toBe(true);
});

test("a failed run explains why, and a run blocked by a draft offers its playbook", async ({ page }) => {
  const conflict = mockPlaybookRun({ status: "FAILED", error_code: "draft_conflict", skill_name: "Refunds" });
  const { playbooks } = await open(page, {
    runs: [mockPlaybookRun({ status: "FAILED", error_code: "spend_limit_reached" }), conflict],
  });

  await expect(playbooks.runs().first()).toContainText("spend limit was reached");
  const blocked = playbooks.runs().nth(1);
  await expect(blocked).toContainText("left untouched");
  await page.route(`**/playbook-extractions/${conflict.id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...conflict, result_markdown: "# Refunds\n\nCheck the order first." }),
    }),
  );
  await blocked.getByRole("button", { name: "View playbook" }).click();

  await expect(page.getByRole("dialog")).toContainText("Check the order first.");
});

test("a run can write the next draft of an existing playbook", async ({ page }) => {
  const { mock, playbooks } = await open(page, {
    runs: [mockSucceededRun({ skill_name: "Refunds playbook" })],
  });

  await playbooks.writeToExistingPlaybook();
  await expect(playbooks.form().getByRole("combobox", { name: "Playbook" })).toContainText("Refunds playbook");
  await playbooks.create();

  await expect
    .poll(() => mock.requests.find((request) => request.method === "POST")?.body)
    .toEqual({ skill_id: MOCK_PLAYBOOK_SKILL_ID, window_days: 30, max_sessions: 20 });
});

test("a Member who can read the Agent sees no Playbooks tab and sends no playbook requests", async ({ page }) => {
  const { mock, playbooks } = await open(page, { role: "MEMBER" });

  await expect(page.getByRole("complementary").getByRole("link", { name: "Chat", exact: true })).toBeVisible();
  await expect(playbooks.tab()).toHaveCount(0);
  expect(mock.requests).toEqual([]);
});

test("a Platform Administrator chooses the playbook extraction model", async ({ page }) => {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
  await data.users.interceptGetOrganizationsRequest();
  const settings = await data.playbooks.interceptPlatformSettings();
  const playbooks = new AgentPlaybooksPage(page);
  await playbooks.gotoPlatformSettings();

  await expect(playbooks.platformModelSummary()).toContainText("GPT-4.1 mini");
  await playbooks.choosePlatformModel("Claude Sonnet");

  await expect(page.getByRole("status")).toContainText("Playbook extraction model saved");
  expect(settings.writes).toEqual([{ model: "openrouter/anthropic/claude-sonnet" }]);
});

test("proposed organization conventions are reviewed and added to a Template's AGENTS.md", async ({ page }) => {
  const run = mockSucceededRun({
    convention_count: 3,
    conventions: [
      { rule: "Use Vilnius time for dates and deadlines.", conversations: 4 },
      { rule: "Ask before changing records.", conversations: 2 },
      { rule: "Tag sales owners by Slack ID.", conversations: 1 },
    ],
  });
  const { playbooks } = await open(page, { runs: [run] });
  const data = new DataSupport(page);
  await data.orgTemplates.interceptGetLineages();
  const posted = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith(`/templates/${MOCK_ORG_TEMPLATE_KEY}/draft/conventions`),
  );
  await page.route(`**/templates/${MOCK_ORG_TEMPLATE_KEY}/draft/conventions`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ template_key: MOCK_ORG_TEMPLATE_KEY, added: 1, already_present: 1 }),
    }),
  );

  const conventions = playbooks.runs().first().getByRole("group", { name: "Organization conventions" });
  await expect(conventions).toContainText("Organization conventions (3)");
  await expect(conventions).toContainText("Rules for every Agent, whatever its role.");
  await conventions.getByRole("button", { name: "Review conventions" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Seen in 4 conversations");
  await dialog.getByRole("checkbox", { name: "Include convention 3" }).click();
  await dialog.getByRole("textbox", { name: "Convention 2" }).fill("Ask for approval before changing records.");
  await dialog.getByRole("button", { name: "Next: choose Templates (2 rules)" }).click();
  await dialog.getByRole("checkbox", { name: "My Custom v2" }).click();
  await dialog.getByRole("button", { name: "Add 2 rules to 1 Template" }).click();

  expect((await posted).postDataJSON()).toEqual({
    rules: ["Use Vilnius time for dates and deadlines.", "Ask for approval before changing records."],
  });
  await expect(dialog.getByRole("list", { name: "Results" })).toContainText(
    "My Custom: 1 added to the draft, 1 already there",
  );
  await expect(dialog.getByRole("link", { name: "Open Template" })).toHaveAttribute(
    "href",
    `/dashboard/${TEST_ORG_ID}/settings/templates/${MOCK_ORG_TEMPLATE_KEY}`,
  );
});

test("a run that proposed no conventions offers no review", async ({ page }) => {
  const { playbooks } = await open(page, { runs: [mockSucceededRun({ convention_count: 0 })] });

  await expect(playbooks.runs().first()).toContainText("Ready to review");
  await expect(playbooks.runs().first()).toContainText("None found in these conversations.");
  await expect(playbooks.runs().first().getByRole("button", { name: /Review conventions/ })).toHaveCount(0);
});

function manyTemplates() {
  const lineage = (key: string, name: string, version: number, inUse: boolean) => ({
    template_key: key,
    template_name: name,
    latest_published_version: version,
    has_draft: false,
    template_source: "custom",
    is_fork: false,
    platform_update_available: false,
    in_use: inUse,
  });
  return [
    lineage("tpl-code", "Code Reviewer V2", 13, true),
    lineage("tpl-sales", "Pipedrive Sales Analyst", 17, true),
    lineage("tpl-metrics-1", "Sales Metrics Tracker", 1, true),
    lineage("tpl-metrics-2", "Sales Metrics Tracker", 2, false),
    ...Array.from({ length: 30 }, (_, i) => lineage(`tpl-old-${i}`, `tommy-019e49${String(i).padStart(2, "0")}`, 1, false)),
  ];
}

async function openTemplateStep(page: Page) {
  const run = mockSucceededRun({
    convention_count: 1,
    conventions: [{ rule: "Use Vilnius time for dates and deadlines.", conversations: 4 }],
  });
  const { playbooks } = await open(page, { runs: [run] });
  await new DataSupport(page).orgTemplates.interceptGetLineages({ body: manyTemplates() });
  await playbooks.runs().first().getByRole("button", { name: "Review conventions" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Next: choose Templates (1 rule)" }).click();
  return dialog;
}

test("the Template step shows Templates Agents use first and can show all of them", async ({ page }) => {
  const dialog = await openTemplateStep(page);
  const templates = dialog.getByRole("list", { name: "Templates" });

  await expect(templates.getByRole("checkbox")).toHaveCount(3);
  await expect(templates.getByRole("listitem").first()).toContainText("Code Reviewer V2");
  await expect(templates).toContainText("In use");

  await dialog.getByRole("checkbox", { name: "Only Templates Agents use" }).click();
  await expect(templates.getByRole("checkbox")).toHaveCount(34);
  await expect(dialog.getByRole("checkbox", { name: "Sales Metrics Tracker v1" })).toBeVisible();
  await expect(dialog.getByRole("checkbox", { name: "Sales Metrics Tracker v2" })).toBeVisible();
});

test("the Template step searches, selects all shown, and keeps hidden choices", async ({ page }) => {
  const dialog = await openTemplateStep(page);

  await dialog.getByRole("searchbox", { name: "Search Templates" }).fill("sales");
  await expect(dialog.getByRole("list", { name: "Templates" }).getByRole("checkbox")).toHaveCount(2);
  await dialog.getByRole("button", { name: "Select all shown" }).click();
  await expect(dialog.getByTestId("selected-template-count")).toHaveText("2 Templates selected");

  await dialog.getByRole("searchbox", { name: "Search Templates" }).fill("code");
  await expect(dialog.getByTestId("selected-template-count")).toHaveText("2 Templates selected (2 not shown)");
  await expect(dialog.getByRole("button", { name: "Add 1 rule to 2 Templates" })).toBeEnabled();

  await dialog.getByRole("button", { name: "Clear" }).click();
  await expect(dialog.getByRole("button", { name: "Add 1 rule to 0 Templates" })).toBeDisabled();
});

test("going back keeps the edited rules and chosen Templates", async ({ page }) => {
  const dialog = await openTemplateStep(page);
  await dialog.getByRole("checkbox", { name: "Code Reviewer V2 v13" }).click();

  await dialog.getByRole("button", { name: "Back" }).click();
  await expect(dialog.getByRole("textbox", { name: "Convention 1" })).toHaveValue(
    "Use Vilnius time for dates and deadlines.",
  );
  await dialog.getByRole("button", { name: "Next: choose Templates (1 rule)" }).click();

  await expect(dialog.getByRole("checkbox", { name: "Code Reviewer V2 v13" })).toBeChecked();
});
