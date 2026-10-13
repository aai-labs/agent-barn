import type { Page, Route } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { MOCK_AGENT_ID } from "./agent-data-support.po";

export const MOCK_PLAYBOOK_SKILL_ID = "dddddddd-0000-4000-8000-0000000000d1";
const MOCK_USER_ID = "11111111-1111-4111-8111-111111111111";

type Json = Record<string, unknown>;
type RecordedRequest = { method: string; url: URL; body: unknown };

export function mockPlaybookRun(overrides: Json = {}): Json {
  return {
    id: `eeeeeeee-0000-4000-8000-${String(Math.floor(Math.random() * 1e12)).padStart(12, "0")}`,
    organization_id: TEST_ORG_ID,
    source_agent_id: MOCK_AGENT_ID,
    source_agent_name: "Sally",
    skill_id: null,
    skill_name: "Sally playbook",
    status: "QUEUED",
    error_code: null,
    window_start: "2026-09-13T10:00:00Z",
    window_end: "2026-10-13T10:00:00Z",
    max_sessions: 20,
    model: null,
    session_count: 0,
    message_count: 0,
    tool_call_count: 0,
    memory_count: 0,
    input_chars: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    cost_usd: null,
    requested_by_user_id: MOCK_USER_ID,
    created_at: "2026-10-13T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

export const mockSucceededRun = (overrides: Json = {}) =>
  mockPlaybookRun({
    status: "SUCCEEDED",
    skill_id: MOCK_PLAYBOOK_SKILL_ID,
    model: "openrouter/openai/gpt-4.1-mini",
    session_count: 20,
    message_count: 41,
    tool_call_count: 137,
    memory_count: 3,
    prompt_tokens: 56_000,
    completion_tokens: 9_000,
    cost_usd: "0.031",
    started_at: "2026-10-13T10:00:01Z",
    finished_at: "2026-10-13T10:01:30Z",
    ...overrides,
  });

export interface PlaybookMock {
  requests: RecordedRequest[];
  runs: Json[];
  /** Replace a run's fields, as the worker would. */
  update: (id: string, fields: Json) => void;
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function page(items: Json[], url: URL) {
  const number = Number(url.searchParams.get("page") ?? "1");
  const size = Number(url.searchParams.get("page_size") ?? "20");
  return { page: number, page_size: size, total: items.length, items: items.slice((number - 1) * size, number * size) };
}

export class PlaybookDataSupport {
  constructor(private page: Page) {}

  /** The Agent-level and Organization-level Playbook Extraction routes, backed by one list of runs. */
  async intercept({
    agentId = MOCK_AGENT_ID,
    runs = [],
    preview = { session_count: 20, message_count: 41, tool_call_count: 137 },
    startStatus = 202,
  }: {
    agentId?: string;
    runs?: Json[];
    preview?: Json;
    startStatus?: number;
  } = {}): Promise<PlaybookMock> {
    const requests: RecordedRequest[] = [];
    const state = [...runs];
    const record = (route: Route) => {
      const request = route.request();
      const entry = { method: request.method(), url: new URL(request.url()), body: request.postDataJSON() };
      requests.push(entry);
      return entry;
    };

    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/playbook-extractions**`, async (route) => {
      const { method, url, body } = record(route);
      const path = url.pathname.replace(/.*\/playbook-extractions/, "");
      if (method === "GET" && path === "/preview") {
        return json(route, 200, {
          window_start: "2026-09-13T10:00:00Z",
          window_end: "2026-10-13T10:00:00Z",
          input_chars: 149_000,
          estimated_input_tokens: 48_000,
          estimated_output_tokens: 10_000,
          model: "openrouter/openai/gpt-4.1-mini",
          ...preview,
        });
      }
      if (method === "GET" && path === "") return json(route, 200, page(state, url));
      if (method === "POST" && path === "") {
        if (startStatus >= 400) {
          return json(route, startStatus, { detail: "A playbook extraction is already running for this Agent." });
        }
        const request = body as Json;
        const run = mockPlaybookRun({
          skill_id: request.skill_id ?? null,
          skill_name: request.skill_name ?? "Existing playbook",
          max_sessions: request.max_sessions,
        });
        state.unshift(run);
        return json(route, 202, run);
      }
      const cancel = path.match(/^\/([^/]+)\/cancel$/);
      if (method === "POST" && cancel) {
        const run = state.find((item) => item.id === cancel[1])!;
        Object.assign(run, { status: "CANCELLED", finished_at: "2026-10-13T10:00:05Z" });
        return json(route, 200, run);
      }
      const detail = path.match(/^\/([^/]+)$/);
      if (method === "GET" && detail) {
        const run = state.find((item) => item.id === detail[1]);
        return run ? json(route, 200, { result_markdown: null, ...run }) : json(route, 404, { detail: "Not found" });
      }
      return route.fallback();
    });

    await this.page.route(`**/api/v1/organizations/*/playbook-extractions?*`, async (route) => {
      const { url } = record(route);
      const skillId = url.searchParams.get("skill_id");
      return json(route, 200, page(skillId ? state.filter((run) => run.skill_id === skillId) : state, url));
    });

    return {
      requests,
      runs: state,
      update: (id, fields) => Object.assign(state.find((run) => run.id === id)!, fields),
    };
  }

  async interceptPlatformSettings({ model = "openrouter/openai/gpt-4.1-mini" } = {}) {
    const writes: unknown[] = [];
    let current = model;
    await this.page.route("**/api/v1/platform/settings/playbooks/models", (route) =>
      json(route, 200, [
        { value: "openrouter/openai/gpt-4.1-mini", label: "GPT-4.1 mini" },
        { value: "openrouter/anthropic/claude-sonnet", label: "Claude Sonnet" },
      ]),
    );
    await this.page.route("**/api/v1/platform/settings/playbooks", async (route) => {
      if (route.request().method() === "PUT") {
        const payload = route.request().postDataJSON();
        writes.push(payload);
        current = payload.model;
      }
      return json(route, 200, { model: current, updated_at: null });
    });
    return { writes };
  }
}
