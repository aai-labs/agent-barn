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
    await expect(ui.integrationsSection().getByRole("alert")).toHaveText("Invalid API key");
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
