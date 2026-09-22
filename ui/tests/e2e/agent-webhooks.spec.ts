import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  MOCK_SIGNING_SECRET,
  mockAgentWebhook,
} from "../fixtures/agent-webhooks";
import { AgentWebhooksPage } from "../pages/agent-webhooks-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Agent Webhooks", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    const dataSupport = new DataSupport(page);
    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({ body: mockAgent });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agentWebhooks.interceptWebhookRequests({
      agentId: MOCK_AGENT_ID,
    });
  });

  test("reveals the signing secret once with a prompt-only example request", async ({
    page,
  }) => {
    const webhooksPage = new AgentWebhooksPage(page);

    await webhooksPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await webhooksPage.createWebhook("CI pipeline");

    await expect(webhooksPage.signingSecret()).toHaveValue(MOCK_SIGNING_SECRET);
    await expect(webhooksPage.exampleRequest()).toContainText(
      `BODY='{"prompt":"Say Hi!"}'`,
    );
    await expect(webhooksPage.exampleRequest()).toContainText(
      `printf '%s.%s' "$TIMESTAMP" "$BODY"`,
    );
    await expect(webhooksPage.exampleRequest()).toContainText(
      "X-AgentBarn-Timestamp: $TIMESTAMP",
    );
    await expect(webhooksPage.exampleRequest()).not.toContainText("event_id");
    await expect(
      page.getByText(/Only prompt is required, up to 5,000 characters/),
    ).toBeVisible();

    await webhooksPage.acknowledgeSecretButton().click();
    await expect(
      page.getByRole("heading", { name: "CI pipeline" }),
    ).toBeVisible();
    await expect(page.getByText(MOCK_SIGNING_SECRET)).toHaveCount(0);
  });

  test("does not repeat the platform when the connection has the same name", async ({
    page,
  }) => {
    await page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/webhooks/delivery-platforms`,
      (route) =>
        route.fulfill({ json: [{ key: "slack", display_name: "Slack" }] }),
    );
    const webhooksPage = new AgentWebhooksPage(page);

    await webhooksPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await page.getByRole("button", { name: "Add webhook" }).click();
    await page.getByRole("combobox", { name: "Deliver results to" }).click();

    await expect(
      page.getByRole("option", { name: "Slack", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("option", { name: "Slack · Slack", exact: true }),
    ).toHaveCount(0);
  });

  test("explains the default-channel requirement when no delivery platform is available", async ({
    page,
  }) => {
    await page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/webhooks/delivery-platforms`,
      (route) => route.fulfill({ json: [] }),
    );
    const webhooksPage = new AgentWebhooksPage(page);

    await webhooksPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await page.getByRole("button", { name: "Add webhook" }).click();

    await expect(
      page.getByRole("region", { name: "Webhooks" }).getByRole("alert"),
    ).toContainText(
      "Configure and enable Slack, Discord, Telegram, or Teams with a default channel before adding a webhook.",
    );
    await expect(
      page.getByText(
        "A default channel is required to post webhook-triggered Agent messages.",
      ),
    ).toBeVisible();
  });

  test("retries a failed submission as a new dispatch generation", async ({
    page,
  }) => {
    const webhooksPage = new AgentWebhooksPage(page);

    await webhooksPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await webhooksPage.createWebhook("CI pipeline");
    await webhooksPage.acknowledgeSecretButton().click();

    await webhooksPage.invocation("Not submitted").click();
    await expect(page.getByText("DISPATCH_TRANSPORT_ERROR")).toBeVisible();
    await webhooksPage.retrySubmissionButton().click();

    await expect(page.getByText("Dispatch generation 2")).toBeVisible();
    await expect(page.getByText("native-job-2")).toBeVisible();
    await expect(webhooksPage.retrySubmissionButton()).toHaveCount(0);
  });

  test("hides secret-issuing actions from editors without secret management", async ({
    page,
  }) => {
    const dataSupport = new DataSupport(page);
    await dataSupport.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: mockAgentAllowedActions.filter(
          (action) => action !== "agent.secret.manage",
        ),
      },
    });
    await page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/webhooks`,
      (route) =>
        route.fulfill({
          json: [
            mockAgentWebhook(MOCK_AGENT_ID, { display_name: "CI pipeline" }),
          ],
        }),
    );
    const webhooksPage = new AgentWebhooksPage(page);

    await webhooksPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await expect(
      page.getByRole("button", { name: /CI pipeline/ }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Add webhook" })).toHaveCount(
      0,
    );

    await page.getByRole("button", { name: /CI pipeline/ }).click();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Rotate secret" }),
    ).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
  });
});
