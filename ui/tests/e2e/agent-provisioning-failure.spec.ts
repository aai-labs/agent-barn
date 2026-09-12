/**
 * A failed start has to reach the person who asked for it.
 *
 * The API recorded a useful failure on the Agent and answered the request with
 * "Failed to start agent <uuid>", so the UI had nothing actionable to show and the
 * cause was only reachable through database or cluster diagnostics. These tests
 * cover the two ways a user meets that failure: the mutation they just triggered,
 * and an Agent already sitting in ERROR when the page loads.
 */

import { expect, test } from "@playwright/test";

import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentInError,
  mockProvisioningError,
  mockRbacProvisioningError,
  mockUnknownProvisioningError,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import { TEST_ORG_ID } from "../constants";

test.describe("Agent provisioning failure", () => {
  let agentDetailPage: AgentDetailPage;
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentTemplateRequest();
    await dataSupport.agents.interceptGetConversationChannelsRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetModelsRequest();
  });

  test("an agent already in ERROR explains itself as soon as the page loads", async () => {
    await dataSupport.agents.interceptGetAgentRequest({ body: mockAgentInError });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "error", reason: mockProvisioningError.summary },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const banner = agentDetailPage.provisioningErrorBanner();
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Namespace quota exhausted");
    await expect(banner).toContainText("run out of resource quota");
    await expect(banner).toContainText("Ask an administrator to free up or raise it");
    await expect(agentDetailPage.provisioningErrorDetail()).toContainText(
      "requests.storage: requested 1Gi, used 30Gi, limit 30Gi",
    );
  });

  test("the explanation survives a reload rather than living in one response", async ({
    page,
  }) => {
    await dataSupport.agents.interceptGetAgentRequest({ body: mockAgentInError });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "error", reason: mockProvisioningError.summary },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await expect(agentDetailPage.provisioningErrorBanner()).toBeVisible();

    await page.reload();

    await expect(agentDetailPage.provisioningErrorBanner()).toBeVisible();
    await expect(agentDetailPage.provisioningErrorBanner()).toContainText(
      "run out of resource quota",
    );
  });

  test("a failed start reports the cause instead of a generic message", async ({
    page,
  }) => {
    // The Agent is stopped, so the page offers Start; the mutation is what fails.
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", running_model: "" },
    });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "ok" },
    });
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await page.getByRole("button", { name: "Start", exact: true }).click();

    const toast = page.getByText("run out of resource quota").first();
    await expect(toast).toBeVisible();
    await expect(page.getByText("Failed to start agent")).toHaveCount(0);
  });

  test("a failed start leaves the recorded failure standing on the page", async ({
    page,
  }) => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", running_model: "" },
    });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "ok" },
    });
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    // The failure response carries no Agent body, so the page has to re-read the
    // Agent to learn it is now in ERROR. From here the API reports the failure.
    await dataSupport.agents.interceptGetAgentRequest({ body: mockAgentInError });
    await page.getByRole("button", { name: "Start", exact: true }).click();

    await expect(agentDetailPage.provisioningErrorBanner()).toBeVisible();
  });

  test("an unclassified failure falls back to generic copy", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgentInError, last_error: mockUnknownProvisioningError },
    });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "error", reason: mockUnknownProvisioningError.summary },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const banner = agentDetailPage.provisioningErrorBanner();
    await expect(banner).toContainText("The agent couldn't start");
    await expect(banner).toContainText("failed unexpectedly");
    await expect(banner).toContainText("Try again");
  });

  test("a cluster permission denial names RBAC and withholds the service account", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgentInError, last_error: mockRbacProvisioningError },
    });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "error", reason: mockRbacProvisioningError.summary },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    const banner = agentDetailPage.provisioningErrorBanner();
    await expect(banner).toContainText("Cluster permission denied");
    await expect(banner).toContainText("missing RBAC permission");
    await expect(banner).toContainText("Ask an administrator to review them");
    await expect(agentDetailPage.provisioningErrorDetail()).toContainText(
      "cannot create deployments",
    );
    await expect(banner).not.toContainText("serviceaccount");
  });

  test("a stopped agent with nothing wrong shows no failure banner", async () => {
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", running_model: "" },
    });
    await dataSupport.agents.interceptGetAgentHealthRequest({
      body: { status: "ok" },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
    await expect(agentDetailPage.provisioningErrorBanner()).toHaveCount(0);
  });
});

/**
 * Apply & Restart stops the Agent, applies the change, then starts it again. When
 * that final start is refused the Agent is left down, so the failure has to reach
 * the user with the same explanation a plain start gives — the call sites report
 * it through a generic toast that shows only `error.message`.
 */
test.describe("Apply & Restart provisioning failure", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a restart refused by the cluster explains itself", async ({
    page,
  }) => {
    const dataSupport = new DataSupport(page);
    const configurationPage = new AgentConfigurationPage(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "RUNNING" },
    });
    await dataSupport.agents.interceptGetAgentConfigurationRequest();
    await dataSupport.agents.interceptGetModelsRequest();
    await dataSupport.agents.interceptGetAgentHealthRequest();
    await dataSupport.agents.interceptUpdateAgentRequest();
    await dataSupport.agents.interceptStopAgentRequest();
    await dataSupport.agents.interceptStartAgentRequest({
      status: 503,
      detail: mockProvisioningError,
    });

    await configurationPage.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configurationPage.sectionButton("Profile").click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Agent name").fill("Maya restarted");

    const footer = page.locator('section[aria-label="Profile"] footer');
    await footer.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply & Restart", exact: true })
      .click();

    await expect(page.getByText("run out of resource quota").first()).toBeVisible();
  });
});
