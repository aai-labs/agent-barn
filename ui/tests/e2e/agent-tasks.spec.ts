import { expect, test, type Page } from "@playwright/test";

import { mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { mockTask } from "../pages/data-support/task-data-support.po";
import { TasksPage } from "../pages/tasks-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

type TaskMockOptions = Parameters<DataSupport["tasks"]["intercept"]>[0];

async function open(
  page: Page,
  {
    allowedActions = [...mockAgentAllowedActions, "task.read"],
    tasks,
    ...mockOptions
  }: { allowedActions?: string[] } & TaskMockOptions = {},
) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, allowed_actions: allowedActions } });
  await data.agents.interceptGetAgentHealthRequest();
  await data.agents.interceptGetConversationChannelsRequest();
  const mock = await data.tasks.intercept({ ...(tasks ? { tasks } : {}), ...mockOptions });
  const tasksPage = new TasksPage(page);
  await tasksPage.gotoAgentTab();
  return { mock, tasksPage };
}

test("the Agent's Tasks are listed with their status", async ({ page }) => {
  const { tasksPage } = await open(page, {
    tasks: [
      mockTask(),
      mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Chase late payments", status: "in_progress" }),
    ],
  });

  await expect(tasksPage.agentTab()).toBeVisible();
  await tasksPage.showList();
  await expect(tasksPage.rows()).toHaveCount(2);
  await expect(tasksPage.rows().filter({ hasText: "Reconcile March invoices" })).toContainText("Done");
  await expect(tasksPage.rows().filter({ hasText: "Chase late payments" })).toContainText("In progress");
});

test("opening a Task shows its notes and downloads its files", async ({ page }) => {
  const { tasksPage } = await open(page);
  await tasksPage.showList();

  await tasksPage.open("Reconcile March invoices");

  await expect(tasksPage.detail()).toContainText("Match every March invoice to a payment");
  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");
  await expect(tasksPage.detail()).toContainText("march-reconciliation.csv");
  await expect(tasksPage.detail()).toContainText("2 KiB");

  const downloading = page.waitForEvent("download");
  await tasksPage.detail().getByRole("button", { name: "Download march-reconciliation.csv" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("march-reconciliation.csv");
});

test("the status filter narrows the list", async ({ page }) => {
  const { mock, tasksPage } = await open(page, {
    tasks: [mockTask(), mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Chase late payments", status: "failed" })],
  });
  await tasksPage.showList();
  await expect(tasksPage.rows()).toHaveCount(2);

  await tasksPage.filterBy("Status", "Failed");

  await expect(tasksPage.rows()).toHaveCount(1);
  await expect(tasksPage.rows().first()).toContainText("Chase late payments");
  expect(mock.listRequests.some((url) => url.searchParams.get("status") === "failed")).toBe(true);
});

test("an Agent without Tasks says so", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: [] });
  await tasksPage.showList();

  await expect(page.getByText("This Agent hasn't recorded any tasks yet.")).toBeVisible();
  await expect(tasksPage.rows()).toHaveCount(0);
});

test("the Tasks tab is hidden without permission to see the Agent's tasks", async ({ page }) => {
  const { tasksPage } = await open(page, { allowedActions: mockAgentAllowedActions });

  await expect(page.getByRole("complementary").getByRole("link", { name: "Overview", exact: true })).toBeVisible();
  await expect(tasksPage.agentTab()).toHaveCount(0);
  await expect(tasksPage.rows()).toHaveCount(0);
});

test("the board is the default view, with a column for each status", async ({ page }) => {
  const { tasksPage } = await open(page, {
    tasks: [
      mockTask(),
      mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Chase late payments", status: "in_progress" }),
      mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a3", title: "Send the April invoices", status: "done" }),
    ],
  });

  await expect(tasksPage.viewButton("Board")).toHaveAttribute("aria-pressed", "true");
  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(2);
  await expect(tasksPage.column("Done")).toContainText("2");
  await expect(tasksPage.column("In progress").getByTestId("task-card")).toHaveCount(1);
  await expect(tasksPage.column("In progress")).toContainText("Chase late payments");
  await expect(tasksPage.column("Open")).toContainText("No tasks.");
  await expect(tasksPage.column("Failed")).toContainText("No tasks.");
  await expect(page.getByRole("combobox", { name: "Status" })).toHaveCount(0);
});

test("a card opens the Task with its notes and files", async ({ page }) => {
  const { tasksPage } = await open(page);

  await tasksPage.openCard("Reconcile March invoices");

  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");
  await expect(tasksPage.detail().getByRole("button", { name: "Download march-reconciliation.csv" })).toBeVisible();
});

test("the chosen view is kept across a reload", async ({ page }) => {
  const { tasksPage } = await open(page);

  await tasksPage.showList();
  await expect(page).toHaveURL(/taskView=list/);
  await page.reload();

  await expect(tasksPage.viewButton("List")).toHaveAttribute("aria-pressed", "true");
  await expect(tasksPage.rows()).toHaveCount(1);
  await expect(tasksPage.cards()).toHaveCount(0);
});

test("a card says what the Task produced, and a failed one says why", async ({ page }) => {
  const { tasksPage } = await open(page, {
    tasks: [
      mockTask({ file_count: 2, note_count: 3 }),
      mockTask({
        id: "aaaaaaaa-0000-4000-8000-0000000000a2",
        title: "Summarise the board deck",
        status: "failed",
        file_count: 0,
        note_count: 1,
        latest_note: "The deck link needs a sign-in",
      }),
    ],
  });

  const done = tasksPage.cards().filter({ hasText: "Reconcile March invoices" });
  await expect(done).toContainText("2 files");
  await expect(done).toContainText("3 notes");
  await expect(done).not.toContainText("Two invoices had no payment");
  await expect(tasksPage.cards().filter({ hasText: "Summarise the board deck" })).toContainText(
    "The deck link needs a sign-in",
  );
});

test("an open Task has its own link", async ({ page }) => {
  const { tasksPage } = await open(page);

  await tasksPage.openCard("Reconcile March invoices");
  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");
  await expect(page).toHaveURL(/task=/);

  await page.reload();
  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");

  await page.keyboard.press("Escape");
  await expect(tasksPage.detail()).toHaveCount(0);
  await expect(page).not.toHaveURL(/task=/);
});

test("a board without Tasks says so once", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: [] });

  await expect(page.getByText("This Agent hasn't recorded any tasks yet.")).toBeVisible();
  await expect(tasksPage.column("Open")).toHaveCount(0);
});

test("Back after closing a Task leaves the page, rather than staying on it", async ({ page }) => {
  const { tasksPage } = await open(page);
  const tabUrl = page.url();

  await tasksPage.openCard("Reconcile March invoices");
  await expect(tasksPage.detail()).toContainText("Two invoices had no payment");
  await page.keyboard.press("Escape");
  await expect(tasksPage.detail()).toHaveCount(0);
  await expect(page).toHaveURL(tabUrl);

  await page.goBack();
  await expect(page).not.toHaveURL(tabUrl);
});

test("leaving the Tasks tab leaves its view and open Task behind", async ({ page }) => {
  const { tasksPage } = await open(page);
  await tasksPage.showList();
  await tasksPage.open("Reconcile March invoices");
  await expect(page).toHaveURL(/taskView=list.*task=|task=.*taskView=list/);
  await page.keyboard.press("Escape");

  await page.getByRole("complementary").getByRole("link", { name: "Overview", exact: true }).click();

  await expect(page).not.toHaveURL(/taskView=|taskStatus=|[?&]task=/);
});

function manyTasks(count: number) {
  return Array.from({ length: count }, (_, index) =>
    mockTask({
      id: `aaaaaaaa-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      title: `Task ${index + 1}`,
      status: "done",
    }),
  );
}

test("a failed Load more keeps the Tasks already shown", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: manyTasks(25), failingPages: [2] });
  await tasksPage.showList();
  await expect(tasksPage.rows()).toHaveCount(20);

  await page.getByRole("button", { name: "Load more" }).click();

  await expect(page.getByText("Could not load more tasks")).toBeVisible();
  await expect(tasksPage.rows()).toHaveCount(20);
});

test("a Task that moves while pages load is shown once", async ({ page }) => {
  const tasks = manyTasks(25);
  const { tasksPage } = await open(page, { tasks });
  await tasksPage.showList();
  await expect(tasksPage.rows()).toHaveCount(20);

  // A new Task arrives at the top, pushing Task 20 onto the next page as well.
  tasks.unshift(mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000ff", title: "Brand new", status: "done" }));
  await page.getByRole("button", { name: "Load more" }).click();

  await expect(tasksPage.rows().filter({ has: page.getByText("Task 20", { exact: true }) })).toHaveCount(1);
  // The first page's 20, then Tasks 21 to 25: Task 20 came back on the second page and is not repeated.
  await expect(tasksPage.rows()).toHaveCount(25);
});

test("the board refreshes while it is open", async ({ page }) => {
  await page.clock.install();
  const tasks = [mockTask({ status: "in_progress" })];
  const { tasksPage } = await open(page, { tasks });
  await expect(tasksPage.column("In progress").getByTestId("task-card")).toHaveCount(1);

  tasks[0] = mockTask({ status: "done" });
  await page.clock.fastForward(31_000);

  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(1);
  await expect(tasksPage.column("In progress").getByTestId("task-card")).toHaveCount(0);
});

test("a Task the Agent's runtime recorded says so", async ({ page }) => {
  const { tasksPage } = await open(page, {
    tasks: [
      mockTask(),
      mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Summarise the thread", origin: "automatic" }),
    ],
  });

  await expect(tasksPage.cards().filter({ hasText: "Summarise the thread" })).toContainText("Recorded automatically");
  await expect(tasksPage.cards().filter({ hasText: "Reconcile March invoices" })).not.toContainText(
    "Recorded automatically",
  );
});

test("an expired file says it has expired", async ({ page }) => {
  const { tasksPage } = await open(page, {
    link: { status: 410, detail: "This file has expired and can no longer be downloaded." },
  });
  await tasksPage.openCard("Reconcile March invoices");

  await tasksPage.detail().getByRole("button", { name: "Download march-reconciliation.csv" }).click();

  await expect(page.getByText("This file has expired and can no longer be downloaded.")).toBeVisible();
});

test("a malformed Task link opens nothing", async ({ page }) => {
  const { tasksPage } = await open(page);

  await page.goto(`${page.url()}&task=foo.bar`);

  await expect(tasksPage.cards()).toHaveCount(1);
  await expect(tasksPage.detail()).toHaveCount(0);
});

const daysAgo = (days: number) => new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

const RECENT_AND_OLD = [
  mockTask({ title: "This week's report", updated_at: daysAgo(3) }),
  mockTask({ id: "aaaaaaaa-0000-4000-8000-0000000000a2", title: "Old report", updated_at: daysAgo(40) }),
  mockTask({
    id: "aaaaaaaa-0000-4000-8000-0000000000a3",
    title: "Waiting on the client",
    status: "open",
    updated_at: daysAgo(60),
  }),
];

test("the board shows the last 30 days of finished work, and every unfinished Task", async ({ page }) => {
  const { mock, tasksPage } = await open(page, { tasks: RECENT_AND_OLD });

  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(1);
  await expect(tasksPage.column("Done")).toContainText("This week's report");
  await expect(tasksPage.column("Open")).toContainText("Waiting on the client");
  await expect(page.getByRole("combobox", { name: "Updated" })).toContainText("Last 30 days");
  const since = (status: string) =>
    mock.listRequests.find((url) => url.searchParams.get("status") === status)?.searchParams.get("updated_since");
  expect(since("done")).toBeTruthy();
  expect(since("open")).toBeFalsy();
});

test("All time brings older finished Tasks back", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: RECENT_AND_OLD });
  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(1);

  await tasksPage.filterBy("Updated", "All time");

  await expect(tasksPage.column("Done").getByTestId("task-card")).toHaveCount(2);
  await expect(page).toHaveURL(/taskPeriod=all/);
});

test("the list keeps to the chosen time too, and says when nothing is that recent", async ({ page }) => {
  const { tasksPage } = await open(page, { tasks: [RECENT_AND_OLD[1]] });
  await tasksPage.showList();

  await expect(page.getByText("No tasks in the last 30 days.")).toBeVisible();
  await tasksPage.filterBy("Updated", "All time");
  await expect(tasksPage.rows()).toHaveCount(1);
});
