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
  await expect(run).toContainText("Draft ready", { timeout: 10_000 });
  await expect(run).toContainText("20 conversations · 41 messages · 137 tool calls · 3 memories · 65.0k tokens");
  await expect(run.getByRole("link", { name: "Review draft" })).toHaveAttribute(
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

  await expect(page.getByRole("button", { name: "Chat", exact: true })).toBeVisible();
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
