import { Page } from "@playwright/test";

import {
  AGENT_WEBHOOK_ID,
  MOCK_SIGNING_SECRET,
  WEBHOOK_INVOCATION_ID,
  mockAgentWebhook,
  mockWebhookDeliveryPlatforms,
  mockWebhookInvocation,
} from "../../fixtures/agent-webhooks";

export class AgentWebhookDataSupport {
  constructor(private page: Page) {}

  /** Stateful mock: create adds the webhook to the list; retry submits the failed invocation. */
  async interceptWebhookRequests({ agentId }: { agentId: string }) {
    const base = `**/api/v1/organizations/*/agents/${agentId}/webhooks`;
    const webhooks: Record<string, unknown>[] = [];
    let invocation = mockWebhookInvocation();

    await this.page.route(base, async (route) => {
      if (route.request().method() === "POST") {
        const created = mockAgentWebhook(agentId, {
          display_name: route.request().postDataJSON().display_name,
        });
        webhooks.push(created);
        await route.fulfill({
          status: 201,
          json: { ...created, signing_secret: MOCK_SIGNING_SECRET },
        });
        return;
      }
      await route.fulfill({ json: webhooks });
    });
    await this.page.route(`${base}/delivery-platforms`, (route) =>
      route.fulfill({ json: mockWebhookDeliveryPlatforms }),
    );
    await this.page.route(
      `${base}/${AGENT_WEBHOOK_ID}/invocations?*`,
      (route) =>
        route.fulfill({
          json: { items: [invocation], total: 1, page: 1, page_size: 20 },
        }),
    );
    await this.page.route(
      `${base}/${AGENT_WEBHOOK_ID}/invocations/${WEBHOOK_INVOCATION_ID}/retry`,
      async (route) => {
        invocation = mockWebhookInvocation({
          status: "SUBMITTED",
          dispatch_generation: 2,
          dispatch_attempt_count: 1,
          native_job_id: "native-job-2",
          last_error_code: null,
          last_error_message: null,
        });
        await route.fulfill({ json: invocation });
      },
    );
  }
}
