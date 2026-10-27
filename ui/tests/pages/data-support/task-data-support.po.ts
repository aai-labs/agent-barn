import type { Page, Route } from "@playwright/test";

import { MOCK_AGENT_ID } from "./agent-data-support.po";

type Json = Record<string, unknown>;

export const MOCK_TASK_ID = "aaaaaaaa-0000-4000-8000-0000000000a1";
export const MOCK_TASK_FILE_ID = "aaaaaaaa-0000-4000-8000-0000000000f1";
export const MOCK_TASK_ARTIFACT_ID = "aaaaaaaa-0000-4000-8000-0000000000c1";

export function mockTask(overrides: Json = {}): Json {
  return {
    id: MOCK_TASK_ID,
    agent_id: MOCK_AGENT_ID,
    title: "Reconcile March invoices",
    description: "Match every March invoice to a payment",
    status: "done",
    origin: "agent",
    created_at: "2026-10-20T09:00:00Z",
    updated_at: "2026-10-20T09:30:00Z",
    ...overrides,
  };
}

export function mockTaskDetail(overrides: Json = {}): Json {
  return {
    ...mockTask(),
    notes: [{ id: "aaaaaaaa-0000-4000-8000-0000000000b1", body: "Two invoices had no payment", created_at: "2026-10-20T09:20:00Z" }],
    files: [
      {
        id: MOCK_TASK_FILE_ID,
        artifact_id: MOCK_TASK_ARTIFACT_ID,
        filename: "march-reconciliation.csv",
        content_type: "text/csv",
        size_bytes: 2048,
        created_at: "2026-10-20T09:29:00Z",
      },
    ],
    ...overrides,
  };
}

export interface TaskMock {
  /** Every Task list request, Agent-level and Organization-level. */
  listRequests: URL[];
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function filtered(tasks: Json[], url: URL) {
  const status = url.searchParams.get("status");
  const agentId = url.searchParams.get("agent_id");
  const items = tasks.filter(
    (task) => (!status || task.status === status) && (!agentId || task.agent_id === agentId),
  );
  return { page: 1, page_size: 20, total: items.length, items };
}

export class TaskDataSupport {
  constructor(private page: Page) {}

  /** The Agent-level and Organization-level Task routes, backed by one list of Tasks. */
  async intercept({
    tasks = [mockTask()],
    detail = mockTaskDetail(),
    fileBody = "invoice,amount\n1,10\n",
  }: { tasks?: Json[]; detail?: Json; fileBody?: string } = {}): Promise<TaskMock> {
    const listRequests: URL[] = [];

    await this.page.route("**/api/v1/organizations/*/tasks**", async (route) => {
      const url = new URL(route.request().url());
      listRequests.push(url);
      return json(route, 200, filtered(tasks, url));
    });

    await this.page.route("**/api/v1/organizations/*/agents/*/tasks**", async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace(/.*\/agents\/[^/]+\/tasks/, "");
      if (path === "") {
        listRequests.push(url);
        const agentId = url.pathname.match(/\/agents\/([^/]+)\/tasks/)![1];
        return json(route, 200, filtered(tasks.filter((task) => task.agent_id === agentId), url));
      }
      if (/^\/[^/]+\/files\/[^/]+\/download-link$/.test(path)) {
        const agentId = url.pathname.match(/\/agents\/([^/]+)\/tasks/)![1];
        return json(route, 200, {
          artifact: {
            id: MOCK_TASK_ARTIFACT_ID,
            filename: "march-reconciliation.csv",
            size: fileBody.length,
            content_type: "text/csv",
            checksum: "sha256",
            state: "READY",
            source: "chat",
            published_at: "2026-10-20T09:29:00Z",
            workflow_id: null,
            run_id: null,
            step_id: null,
            attempt_id: null,
          },
          url: `${url.origin}/api/v1/agent-artifacts/org/${agentId}/${MOCK_TASK_ARTIFACT_ID}?access=signed`,
          expires_at: "2026-10-20T09:45:00Z",
        });
      }
      if (/^\/[^/]+$/.test(path)) return json(route, 200, detail);
      return route.fallback();
    });

    // The signed link the Artifacts download route serves.
    await this.page.route("**/api/v1/agent-artifacts/**", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "content-type": "text/csv",
          "content-disposition": 'attachment; filename="march-reconciliation.csv"',
        },
        body: fileBody,
      }),
    );

    return { listRequests };
  }
}
