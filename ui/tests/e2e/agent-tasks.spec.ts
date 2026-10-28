import { expect, test, type Page } from "@playwright/test";

import { mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { mockTask } from "../pages/data-support/task-data-support.po";
import { TasksPage } from "../pages/tasks-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

async function open(page: Page, { allowedActions = [...mockAgentAllowedActions, "task.read"], tasks }: { allowedActions?: string[]; tasks?: Record<string, unknown>[] } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, allowed_actions: allowedActions } });
  await data.agents.interceptGetAgentHealthRequest();
  await data.agents.interceptGetConversationChannelsRequest();
  const mock = await data.tasks.intercept(tasks ? { tasks } : {});
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
