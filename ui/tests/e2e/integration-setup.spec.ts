import { expect, test } from "@playwright/test";

import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import { IntegrationSetupDataSupport } from "../pages/data-support/integration-setup-data-support.po";

test.describe("Credential apply before restart", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a rejected credential leaves the running Agent alone and can be corrected", async ({ page }) => {
    const data = new IntegrationSetupDataSupport(page);
    const ui = new AgentConfigurationPage(page);
    await data.open();
    await ui.addApolloCredential("rejected-key");
    await ui.applyIntegrations();
    await expect(ui.integrationCard("Apollo").getByRole("alert")).toContainText("Apollo credential: Invalid API key");
    await expect(ui.integrationsSection()).toContainText("No changes were saved. Your agent is still running.");
    expect(data.lifecycleRequests).toEqual([]);
    expect(data.requests).toHaveLength(1);
    expect(data.requests[0]).toMatchObject({ restart: true, secrets: [{ provider: "apollo", content: { api_token: "rejected-key" } }] });
    await expect(ui.apolloKey()).toHaveValue("rejected-key");

    await ui.apolloKey().fill("accepted-key");
    await ui.applyIntegrations();
    await expect(ui.integrationsSection().getByRole("button", { name: "Edit", exact: true })).toBeVisible();
    expect(data.requests).toHaveLength(2);
    expect(data.lifecycleRequests).toEqual([]);
  });

  test("identifies a failing integration after another integration and keeps both drafts", async ({ page }) => {
    const data = new IntegrationSetupDataSupport(page);
    const ui = new AgentConfigurationPage(page);
    await data.open();
    await ui.addFirecrawlCredential("fc-fixture-key");
    await ui.appendApolloCredential("rejected-key");
    await ui.integrationCard("Apollo").locator("summary").click();
    await ui.applyIntegrations();

    await expect(ui.integrationCard("Apollo").getByRole("alert")).toContainText("Apollo credential: Invalid API key");
    await expect(ui.integrationCard("Firecrawl").getByRole("alert")).toHaveCount(0);
    await expect(ui.integrationsSection()).toContainText("No changes were saved. Your agent is still running.");
    await expect(ui.integrationKey("Firecrawl")).toHaveValue("fc-fixture-key");
    await expect(ui.apolloKey()).toHaveValue("rejected-key");
    expect(data.requests[0].secrets).toHaveLength(2);
    expect(data.lifecycleRequests).toEqual([]);
  });

  test("a rejected credential on a stopped Agent does not claim it is running", async ({ page }) => {
    const data = new IntegrationSetupDataSupport(page);
    const ui = new AgentConfigurationPage(page);
    await data.open({ running: false });
    await ui.addApolloCredential("rejected-key");
    await ui.applyIntegrations();
    await expect(ui.integrationCard("Apollo").getByRole("alert")).toContainText("Apollo credential: Invalid API key");
    await expect(ui.integrationsSection()).toContainText("No changes were saved.");
    await expect(ui.integrationsSection()).not.toContainText("still running");
    expect(data.lifecycleRequests).toEqual([]);
  });

  test("a stopped Agent saves credentials without requesting a start", async ({ page }) => {
    const data = new IntegrationSetupDataSupport(page);
    const ui = new AgentConfigurationPage(page);
    await data.open({ running: false, reject: false });
    await ui.addApolloCredential("accepted-key");
    await ui.applyIntegrations();
    await expect(ui.integrationsSection().getByRole("button", { name: "Edit", exact: true })).toBeVisible();
    expect(data.requests[0]).toMatchObject({ restart: false });
    expect(data.lifecycleRequests).toEqual([]);
  });
});
