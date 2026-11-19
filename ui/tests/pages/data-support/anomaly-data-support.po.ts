import type { Page, Route } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import { MOCK_AGENT_ID } from "./agent-data-support.po";

type Json = Record<string, unknown>;
type RecordedRequest = { method: string; url: URL; body: unknown };

export function mockAnomaly(overrides: Json = {}): Json {
  return {
    id: `aaaaaaaa-0000-4000-8000-${String(Math.floor(Math.random() * 1e12)).padStart(12, "0")}`,
    signal: "TOOL_CALLS_PER_HOUR",
    subject: null,
    observed_value: 400,
    usual_value: 100,
    threshold: 152,
    started_at: "2026-11-16T09:15:00Z",
    last_observed_at: "2026-11-16T10:28:00Z",
    ended_at: null,
    classification_state: "STATISTICS_ONLY",
    classification: null,
    ...overrides,
  };
}

export function mockNormalBehaviour(overrides: Json = {}): Json {
  return {
    detection_enabled: true,
    enough_history: true,
    active_days: 9,
    rates: [
      { signal: "TOOL_CALLS_PER_HOUR", usual: 100, threshold: 152, active_hours: 61 },
      { signal: "LLM_TOKENS_PER_HOUR", usual: 42_000, threshold: 87_000, active_hours: 61 },
    ],
    tools: ["exec", "web_fetch"],
    integrations: ["crm"],
    integration_actions: ["crm read"],
    destinations: ["docs.example.com"],
    override: { sensitivity: "NORMAL", max_llm_tokens_per_hour: null, max_llm_calls_per_hour: null },
    can_manage: true,
    ...overrides,
  };
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export interface AnomalyMock {
  requests: RecordedRequest[];
}

export class AnomalyDataSupport {
  constructor(private page: Page) {}

  /** The Organization's opt-in: reads return the current value, writes store it. */
  async interceptDetection({
    enabled = false,
    canManage = true,
    organizationId = TEST_ORG_ID,
  }: { enabled?: boolean; canManage?: boolean; organizationId?: string } = {}): Promise<AnomalyMock> {
    const mock: AnomalyMock = { requests: [] };
    let current = enabled;
    await this.page.route(`**/api/v1/organizations/${organizationId}/anomaly-detection`, async (route) => {
      const request = route.request();
      const body = request.postDataJSON?.() ?? null;
      mock.requests.push({ method: request.method(), url: new URL(request.url()), body });
      if (request.method() === "PUT") current = Boolean((body as Json).enabled);
      return json(route, 200, { enabled: current, can_manage: canManage, updated_at: null });
    });
    return mock;
  }

  /** One Agent's Anomalies, its learned normal, and override writes. */
  async interceptAgent({
    anomalies = [],
    normal = mockNormalBehaviour(),
    agentId = MOCK_AGENT_ID,
    organizationId = TEST_ORG_ID,
  }: { anomalies?: Json[]; normal?: Json; agentId?: string; organizationId?: string } = {}): Promise<AnomalyMock> {
    const mock: AnomalyMock = { requests: [] };
    const base = `**/api/v1/organizations/${organizationId}/agents/${agentId}`;
    let current = normal;
    await this.page.route(`${base}/anomalies**`, async (route) => {
      const url = new URL(route.request().url());
      mock.requests.push({ method: route.request().method(), url, body: null });
      const page = Number(url.searchParams.get("page") ?? 1);
      const pageSize = Number(url.searchParams.get("page_size") ?? 50);
      const items = anomalies.slice((page - 1) * pageSize, page * pageSize);
      return json(route, 200, { page, page_size: pageSize, total: anomalies.length, items });
    });
    await this.page.route(`${base}/normal-behaviour`, async (route) => {
      mock.requests.push({ method: "GET", url: new URL(route.request().url()), body: null });
      return json(route, 200, current);
    });
    await this.page.route(`${base}/anomaly-override`, async (route) => {
      const body = route.request().postDataJSON();
      mock.requests.push({ method: "PUT", url: new URL(route.request().url()), body });
      current = { ...current, override: body };
      return json(route, 200, body);
    });
    return mock;
  }
}
