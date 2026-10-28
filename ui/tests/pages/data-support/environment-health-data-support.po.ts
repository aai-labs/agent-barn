import { Page } from "@playwright/test";

export const ENV_ACME_ID = "00000000-0000-7000-8000-0000000000aa";
export const ENV_ADA_ID = "11111111-1111-4111-8111-111111111111";
export const ENV_CY_ID = "22222222-2222-4222-8222-222222222222";
export const ENV_ORPHAN_ID = "99999999-9999-4999-8999-999999999999";

const GIB = 1024 ** 3;
const NOW = new Date().toISOString();

const ada = {
  agent_id: ENV_ADA_ID,
  agent_name: "Ada",
  organization_id: ENV_ACME_ID,
  organization_name: "Acme",
  status: "RUNNING",
};
const cy = { ...ada, agent_id: ENV_CY_ID, agent_name: "Cy", status: "ERROR" };

/**
 * The staging incident, as the API reports it: storage is full, so a new agent failed to
 * start, while the platform's services and the other pods look healthy.
 */
export function mockEnvironmentHealth(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    observed_at: NOW,
    namespace: "agent-farm-staging",
    level: "critical",
    sources: [
      { source: "pods", state: "available" },
      { source: "deployments", state: "available" },
      { source: "stateful_sets", state: "available" },
      { source: "volume_claims", state: "available" },
      { source: "resource_quotas", state: "forbidden" },
      { source: "events", state: "forbidden" },
      { source: "prometheus", state: "available" },
    ],
    ceilings: {
      limits_memory_bytes: 52 * GIB,
      limits_cpu_cores: 30,
      requests_memory_bytes: 20 * GIB,
      requests_cpu_cores: 5,
      requests_storage_bytes: 30 * GIB,
      pods: null,
      updated_at: "2026-10-01T12:00:00Z",
    },
    services: [
      { name: "agentbarn-api", kind: "Deployment", desired_replicas: 1, ready_replicas: 1, level: "ok" },
      { name: "postgres-app", kind: "StatefulSet", desired_replicas: 1, ready_replicas: 1, level: "ok" },
    ],
    alerts: [{ name: "AgentsInErrorState", severity: "warning", agent: null }],
    capacity: [
      {
        resource: "requests.storage",
        unit: "bytes",
        source: "entered",
        used: 30 * GIB,
        hard: 30 * GIB,
        ratio: 1,
        level: "critical",
      },
      { resource: "pods", unit: "count", source: "entered", used: 24, hard: null, ratio: null, level: "unknown" },
      {
        resource: "limits.memory",
        unit: "bytes",
        source: "entered",
        used: 30 * GIB,
        hard: 52 * GIB,
        ratio: 30 / 52,
        level: "ok",
      },
    ],
    volumes: {
      total_claims: 3,
      total_requested_bytes: 12 * GIB,
      groups: [
        { group: "infrastructure", claims: 1, requested_bytes: 10 * GIB },
        { group: "active_agents", claims: 1, requested_bytes: GIB },
        { group: "stopped_agents", claims: 0, requested_bytes: 0 },
        { group: "restore_points", claims: 0, requested_bytes: 0 },
        { group: "orphaned", claims: 1, requested_bytes: GIB },
      ],
      attention: [
        {
          name: `agent-${ENV_ORPHAN_ID}`,
          group: "orphaned",
          phase: "Bound",
          requested_bytes: GIB,
          agent: { agent_id: ENV_ORPHAN_ID, agent_name: null, organization_id: null, organization_name: null, status: null },
          created_at: "2026-10-01T12:00:00Z",
        },
      ],
    },
    workloads: {
      pods_total: 24,
      pods_ready: 23,
      issues: [
        {
          pod_name: `agent-${ENV_ADA_ID}-7d9f-abcde`,
          workload_name: `agent-${ENV_ADA_ID}`,
          kind: "agent",
          agent: ada,
          phase: "Running",
          ready: false,
          unschedulable: false,
          restart_count: 6,
          repeatedly_restarting: true,
          waiting_reason: "CrashLoopBackOff",
          termination_reason: "OOMKilled",
          last_restart_at: NOW,
          created_at: "2026-10-01T12:00:00Z",
        },
      ],
    },
    unhealthy_runtimes: [{ agent: ada, pod_ready: true, ever_connected: false }],
    failed_agents: [
      {
        agent: cy,
        code: "QUOTA_EXHAUSTED",
        summary:
          "The agent could not start — its namespace has run out of resource quota. Ask an administrator to free up or raise it.",
        detail: "requests.storage: requested 1Gi, used 30Gi, limit 30Gi",
        updated_at: NOW,
      },
    ],
    events: [],
    ...overrides,
  };
}

export class EnvironmentHealthDataSupport {
  constructor(private page: Page) {}

  /** Answers the page's one request. Returns how many times it was asked. */
  async interceptEnvironmentHealth({
    body = mockEnvironmentHealth(),
    status = 200,
  }: { body?: Record<string, unknown>; status?: number } = {}): Promise<{ count: number }> {
    const calls = { count: 0 };
    await this.page.route("**/api/v1/platform/environment-health", async (route) => {
      calls.count += 1;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail: "Environment health is unavailable" } : body),
      });
    });
    return calls;
  }
}
