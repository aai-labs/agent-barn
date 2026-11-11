import type { Page, Route } from "@playwright/test";

import { mockFileSyncStatus } from "../../fixtures/file-sync";
import { MOCK_AGENT_ID } from "./agent-data-support.po";

export type FileSyncRequest = { method: string; body: unknown };

export type FileSyncActivityMock = {
  requestedPages: number[];
  /** Answer every following history read with this HTTP status, or recover with 200. */
  failReadsWith: (status: number) => void;
};

export type FileSyncMock = {
  requests: FileSyncRequest[];
  /** Answer every following status read with this HTTP status, or recover with 200. */
  failReadsWith: (status: number) => void;
};

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/** Route mocks for an Agent's File Sync. Stateful, so turning sync off shows on the next read. */
export class FileSyncDataSupport {
  constructor(private page: Page) {}

  async interceptFileSync({
    agentId = MOCK_AGENT_ID,
    status = mockFileSyncStatus(),
    readStatus = 200,
  }: {
    agentId?: string;
    status?: Record<string, unknown>;
    readStatus?: number;
  } = {}): Promise<FileSyncMock> {
    let current = { ...status };
    let readsAnswer = readStatus;
    const mock: FileSyncMock = {
      requests: [],
      failReadsWith: (next) => {
        readsAnswer = next;
      },
    };
    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/file-sync`, async (route) => {
      const request = route.request();
      const method = request.method();
      const body = request.postData() ? JSON.parse(request.postData() as string) : null;
      if (method === "GET") {
        mock.requests.push({ method, body });
        if (readsAnswer >= 400) return json(route, readsAnswer, { detail: "Unable to load file sync" });
        return json(route, 200, current);
      }
      if (method === "PUT") {
        mock.requests.push({ method, body });
        const enabled = (body as { enabled: boolean }).enabled;
        current = { ...current, enabled, state: enabled ? "setting_up" : "turned_off" };
        return json(route, 200, { agent_id: agentId, enabled });
      }
      return route.fallback();
    });
    return mock;
  }

  interceptFileSyncActivity(options: Parameters<typeof interceptFileSyncActivity>[1] = {}) {
    return interceptFileSyncActivity(this.page, options);
  }
}

export async function interceptFileSyncActivity(
  page: Page,
  {
    agentId = MOCK_AGENT_ID,
    entries = [],
    readStatus = 200,
  }: { agentId?: string; entries?: Record<string, unknown>[]; readStatus?: number } = {},
): Promise<FileSyncActivityMock> {
  let readsAnswer = readStatus;
  const mock: FileSyncActivityMock = {
    requestedPages: [],
    failReadsWith: (next) => {
      readsAnswer = next;
    },
  };
  await page.route(`**/api/v1/organizations/*/agents/${agentId}/file-sync/activity**`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const url = new URL(route.request().url());
    const pageNumber = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "20");
    mock.requestedPages.push(pageNumber);
    if (readsAnswer >= 400) return json(route, readsAnswer, { detail: "Unable to load file sync history" });
    const start = (pageNumber - 1) * pageSize;
    return json(route, 200, {
      page: pageNumber,
      page_size: pageSize,
      total: entries.length,
      items: entries.slice(start, start + pageSize),
    });
  });
  return mock;
}
