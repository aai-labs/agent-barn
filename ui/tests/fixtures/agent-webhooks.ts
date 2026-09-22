export const AGENT_WEBHOOK_ID = "c0ffee00-0000-4000-8000-000000000001";
export const WEBHOOK_INVOCATION_ID = "c0ffee00-0000-4000-8000-000000000002";
export const MOCK_SIGNING_SECRET = "whsec_test_only_not_a_real_secret";

export function mockAgentWebhook(agentId: string, overrides: Record<string, unknown> = {}) {
  return {
    id: AGENT_WEBHOOK_ID,
    agent_id: agentId,
    display_name: "CI pipeline",
    delivery_platform: "slack",
    enabled: true,
    revision: 1,
    webhook_url: `https://api.example.test/agent-hooks/v1/${AGENT_WEBHOOK_ID}`,
    signing_secret: null,
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:00Z",
    ...overrides,
  };
}

export const mockWebhookDeliveryPlatforms = [{ key: "slack", display_name: "Acme Slack" }];

export function mockWebhookInvocation(overrides: Record<string, unknown> = {}) {
  return {
    id: WEBHOOK_INVOCATION_ID,
    webhook_id: AGENT_WEBHOOK_ID,
    external_event_id: null,
    prompt: "Prepare a release summary.",
    status: "DISPATCH_FAILED",
    dispatch_attempt_count: 3,
    dispatch_generation: 1,
    submitted_at: null,
    native_job_id: null,
    last_error_code: "DISPATCH_TRANSPORT_ERROR",
    last_error_message: "Agent trigger endpoint could not be reached",
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:00Z",
    ...overrides,
  };
}
