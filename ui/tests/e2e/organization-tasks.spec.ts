import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { mockTask } from "../pages/data-support/task-data-support.po";
import { TasksPage } from "../pages/tasks-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

const OTHER_AGENT_ID = "44444444-4444-4444-8444-444444444444";
const TASK_READER_ACTIONS = [...mockAgentAllowedActions, "task.read"];

async function open(page: Page, { tasks }: { tasks?: Record<string, unknown>[] } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentsRequest({
    body: {
      page: 1,
      page_size: 50,
      total: 3,
      items: [
        { ...mockAgent, name: "Maya", allowed_actions: TASK_READER_ACTIONS },
        { ...mockAgent, id: OTHER_AGENT_ID, name: "Rex", allowed_actions: TASK_READER_ACTIONS },
        { ...mockAgent, id: "55555555-5555-4555-8555-555555555555", name: "Orin", allowed_actions: mockAgentAllowedActions },
      ],
    },
  });
  const mock = await data.tasks.intercept(
    tasks
      ? { tasks }
      : {
          tasks: [
            mockTask(),
            mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", agent_id: OTHER_AGENT_ID, title: "Review pull requests", status: "in_progress" }),
          ],
        },
  );
  const tasksPage = new TasksPage(page);
  await tasksPage.gotoOrganization();
  return { mock, tasksPage };
}

test("the Organization's Tasks are listed with the Agent that did them", async ({ page }) => {
  const { tasksPage } = await open(page);
  await tasksPage.showList();

  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(tasksPage.rows()).toHaveCount(2);
  await expect(tasksPage.rows().filter({ hasText: "Reconcile March invoices" })).toContainText("Maya");
  await expect(tasksPage.rows().filter({ hasText: "Review pull requests" })).toContainText("Rex");
  await expect(tasksPage.rows().filter({ hasText: "Review pull requests" })).toContainText("In progress");
});

test("the Agent and status filters narrow the list", async ({ page }) => {
  const { mock, tasksPage } = await open(page);
  await tasksPage.showList();
  await expect(tasksPage.rows()).toHaveCount(2);

  await tasksPage.filterBy("Agent", "Rex");
  await expect(tasksPage.rows()).toHaveCount(1);
  await expect(tasksPage.rows().first()).toContainText("Review pull requests");
  await expect(page).toHaveURL(new RegExp(`agent=${OTHER_AGENT_ID}`));

  await tasksPage.filterBy("Status", "Done");
  await expect(tasksPage.rows()).toHaveCount(0);
  await expect(page.getByText("No tasks match these filters.")).toBeVisible();
  expect(
    mock.listRequests.some(
      (url) => url.searchParams.get("agent_id") === OTHER_AGENT_ID && url.searchParams.get("status") === "done",
    ),
  ).toBe(true);
});

test("only Agents whose tasks the viewer can see are offered as a filter", async ({ page }) => {
  const { tasksPage } = await open(page);
  await expect(tasksPage.cards()).toHaveCount(2);

  await page.getByRole("combobox", { name: "Agent" }).click();

  await expect(page.getByRole("option", { name: "Maya" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Rex" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Orin" })).toHaveCount(0);
});

test("a Task opens with its notes and files", async ({ page }) => {
  const { tasksPage } = await open(page);
  await tasksPage.showList();

  await tasksPage.open("Reconcile March invoices");

  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");
  await expect(tasksPage.detail().getByRole("button", { name: "Download march-reconciliation.csv" })).toBeVisible();
});

test("an Organization without Tasks says so", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: [] });
  await tasksPage.showList();

  await expect(page.getByText("Your Agents haven't recorded any tasks yet.")).toBeVisible();
});

test("the rail links to the Tasks page", async ({ page }) => {
  const { tasksPage } = await open(page);

  await expect(tasksPage.railEntry()).toHaveAttribute("href", `/dashboard/${TEST_ORG_ID}/tasks`);
});

test("the page lists across Agents until one is chosen", async ({ page }) => {
  const { mock } = await open(page);

  await expect.poll(() => mock.listRequests.length).toBeGreaterThan(0);
  expect(mock.listRequests[0].searchParams.get("agent_id")).toBeNull();
  expect(mock.listRequests[0].pathname).not.toContain(`/agents/${MOCK_AGENT_ID}/`);
});

test("the board shows each Agent's Tasks by status and follows the Agent filter", async ({ page }) => {
  const { tasksPage } = await open(page);

  await expect(tasksPage.column("Done")).toContainText("Reconcile March invoices");
  await expect(tasksPage.column("Done")).toContainText("Maya");
  await expect(tasksPage.column("In progress")).toContainText("Review pull requests");
  await expect(tasksPage.column("In progress")).toContainText("Rex");

  await tasksPage.filterBy("Agent", "Rex");

  await expect(tasksPage.cards()).toHaveCount(1);
  await expect(tasksPage.column("Done")).toContainText("No tasks.");
  await expect(page).toHaveURL(new RegExp(`agent=${OTHER_AGENT_ID}`));
});

test("the Task dialog names the Agent and links to its Tasks", async ({ page }) => {
  const { tasksPage } = await open(page);

  await tasksPage.openCard("Reconcile March invoices");

  await expect(tasksPage.detail().getByRole("link", { name: "Maya" })).toHaveAttribute(
    "href",
    `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=tasks`,
  );
});

test("Agents past the first page of the Agents list are named and offered as a filter", async ({ page }) => {
  const { tasksPage } = await open(page);
  // Later routes win: serve the Agents one per page, so Rex is only on page 2.
  await page.route("**/api/v1/organizations/*/agents?*", async (route) => {
    const url = new URL(route.request().url());
    const agents = [
      { ...mockAgent, name: "Maya", allowed_actions: TASK_READER_ACTIONS },
      { ...mockAgent, id: OTHER_AGENT_ID, name: "Rex", allowed_actions: TASK_READER_ACTIONS },
    ];
    const number = Number(url.searchParams.get("page") ?? "1");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ page: number, page_size: 1, total: agents.length, items: agents.slice(number - 1, number) }),
    });
  });
  await page.reload();

  await expect(tasksPage.column("In progress")).toContainText("Rex");
  await page.getByRole("combobox", { name: "Agent" }).click();
  await expect(page.getByRole("option", { name: "Rex" })).toBeVisible();
});

test("Agents that could not be loaded are reported with a retry", async ({ page }) => {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentsRequest({ status: 500 });
  await data.tasks.intercept();
  const tasksPage = new TasksPage(page);

  await tasksPage.gotoOrganization();

  await expect(page.getByText("Could not load your Agents")).toBeVisible();
  await expect(page.getByRole("button", { name: /retry|try again/i }).first()).toBeVisible();
  await expect(tasksPage.cards()).toHaveCount(1);
});

test("a malformed Agent filter in the link is ignored", async ({ page }) => {
  const { mock, tasksPage } = await open(page);

  await page.goto(`/dashboard/${TEST_ORG_ID}/tasks?agent=abc`);

  await expect(tasksPage.cards()).toHaveCount(2);
  expect(mock.listRequests.some((url) => url.searchParams.get("agent_id") === "abc")).toBe(false);
});

test("the Organization board also shows the last 30 days of finished work, or a picked range", async ({ page }) => {
  const daysAgo = (days: number) => new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const { tasksPage } = await open(page, {
    tasks: [
      mockTask({ title: "This week's report", updated_at: daysAgo(3) }),
      mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Old report", updated_at: daysAgo(40) }),
    ],
  });

  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Date range" })).toContainText("Last 30 days");
  await page.goto(`/dashboard/${TEST_ORG_ID}/tasks?from=${daysAgo(50)}&to=${daysAgo(30)}`);
  await expect(tasksPage.column("Done")).toContainText("Old report");
  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(1);
});
