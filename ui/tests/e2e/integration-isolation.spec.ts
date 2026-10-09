import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

async function open(page: Page, options: { provider?: string; status?: string; actions?: string[]; fail?: boolean; supported?: boolean; desired?: boolean; lastVerified?: boolean; reconnectRequired?: boolean; source?: string; provisioning?: boolean } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentConfigurationRequest();
  await data.agents.interceptGetAgentHealthRequest();
  await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
  const provider = options.provider ?? "github";
  const google = provider === "google_workspace";
  const names: Record<string, string> = { github: "GitHub credential", google_workspace: "Google Workspace credential", sharepoint: "SharePoint credential", firecrawl: "Platform Firecrawl" };
  let agent = { ...mockAgent, status: options.status ?? "STOPPED", allowed_actions: options.actions ?? mockAgentAllowedActions,
    secrets: [{ provider, secret_name: names[provider], source: options.source ?? "agent_secret", isolation: {
      desired: options.desired ?? false, applied: options.status === "RUNNING" && !options.provisioning ? false : null,
      last_verified: options.lastVerified ?? null, reconnect_required: options.reconnectRequired ?? false,
      generation: options.provisioning ? "44444444-4444-4444-8444-444444444444" : null, pending: options.provisioning || options.status !== "RUNNING", switch_available: options.supported ?? true,
      supported_modes: ["direct", "isolated"],
      direct_description: google ? "This Agent receives the Google refresh token and OAuth client credentials and connects to Google directly." : "This Agent receives the GitHub token and connects to GitHub directly.",
      isolated_description: google ? "This Agent receives expiring Google access tokens only; the refresh token and OAuth client secret stay outside it." : "The GitHub token stays outside this Agent; Agent Barn authenticates requests.",
    } }],
  };
  const requests: unknown[] = [];
  let reads = 0;
  await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`, (route) => {
    if (options.provisioning && ++reads >= 3) {
      agent = { ...agent, secrets: agent.secrets.map((secret) => ({ ...secret, isolation: {
        ...secret.isolation, applied: true, pending: false,
      } })) };
    }
    return route.fulfill({ json: agent });
  });
  await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/integrations/${provider}/isolation`, async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    if (options.fail) return route.fulfill({ status: 500, json: { detail: "The runtime could not start. Retry the selected mode." } });
    agent = { ...agent, secrets: agent.secrets.map((secret) => ({ ...secret, isolation: { ...secret.isolation,
      desired: body.isolated, applied: body.restart ? body.isolated : null, pending: !body.restart,
    } })) };
    await route.fulfill({ json: agent });
  });
  await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=keys`);
  await expect(page.getByRole("switch")).toHaveCount(0);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.locator("summary").filter({ hasText: google ? "Google Workspace" : provider === "sharepoint" ? "SharePoint" : provider === "firecrawl" ? "Firecrawl" : "GitHub" }).click();
  return requests;
}

test.describe("Credential isolation", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("defaults off and applies a provider-specific choice without starting a stopped Agent", async ({ page }) => {
    const requests = await open(page);
    const control = page.getByRole("switch", { name: "GitHub credential isolation" });
    await expect(control).not.toBeChecked();
    await control.click();
    await expect(page.getByText("GitHub token stays outside", { exact: false })).toBeVisible();
    expect(requests).toEqual([]);
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply", exact: true }).click();
    await expect(page.getByRole("switch")).toHaveCount(0);
    expect(requests).toEqual([{ isolated: true, restart: false }]);
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.locator("summary").filter({ hasText: "GitHub" }).click();
    await expect(page.getByText("Runtime mode has not been verified.", { exact: false })).toBeVisible();
  });

  test("cancel discards isolation without sending a request", async ({ page }) => {
    const requests = await open(page);
    await page.getByRole("switch").click();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(requests).toEqual([]);
    await expect(page.getByRole("switch")).toHaveCount(0);
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.locator("summary").filter({ hasText: "GitHub" }).click();
    await expect(page.getByRole("switch")).not.toBeChecked();
  });

  for (const fail of [false, true]) {
    test(`credential replacement and isolation save ${fail ? "preserves a stopped Agent on failure" : "restart once after both saves"}`, async ({ page }) => {
      const requests = await open(page, { status: "RUNNING", fail });
      const sequence: string[] = [];
      const agentUrl = `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}`;
      await page.route(`${agentUrl}/stop`, (route) => {
        sequence.push("stop");
        return route.fulfill({ json: { ...mockAgent, status: "STOPPED" } });
      });
      await page.route(`${agentUrl}/start`, (route) => {
        sequence.push("start");
        return route.fulfill({ json: mockAgent });
      });
      await page.route(agentUrl, (route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        sequence.push("credentials");
        return route.fulfill({ json: { ...mockAgent, status: "STOPPED" } });
      });
      await page.getByRole("button", { name: "Replace credential" }).click();
      await page.getByPlaceholder("github_pat_… or ghp_…").fill("fixture-token");
      await page.getByPlaceholder("owner-or-org").fill("fixture-org");
      await page.getByRole("switch").click();
      await page.getByRole("button", { name: "Apply & Restart", exact: true }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();
      if (fail) {
        await expect(page.getByRole("alert").filter({ hasText: "runtime could not start" }).first()).toBeVisible();
        expect(sequence).toEqual(["stop", "credentials"]);
      } else {
        await expect.poll(() => sequence).toEqual(["stop", "credentials", "start"]);
        await expect(page.getByRole("switch")).toHaveCount(0);
      }
      expect(requests).toEqual([{ isolated: true, restart: false }]);
    });
  }

  test("Google copy describes expiring access and explicitly restarts a running Agent", async ({ page }) => {
    const requests = await open(page, { provider: "google_workspace", status: "RUNNING" });
    await page.getByRole("switch").click();
    await expect(page.getByText("expiring Google access tokens", { exact: false })).toBeVisible();
    expect(requests).toEqual([]);
    await page.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await expect(page.getByRole("switch")).toHaveCount(0);
    expect(requests).toEqual([{ isolated: true, restart: true }]);
  });

  test("a failed application keeps the current mode and exposes the failure", async ({ page }) => {
    await open(page, { status: "RUNNING", fail: true });
    await page.getByRole("switch").click();
    await page.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "runtime could not start" }).first()).toBeVisible();
    await expect(page.getByRole("switch")).toBeChecked();
    await expect(page.getByText("Current runtime: direct.", { exact: false })).toBeVisible();
  });

  test("requires credential, configuration and lifecycle permission", async ({ page }) => {
    await open(page, { status: "RUNNING", actions: ["agent.read", "agent.update", "agent.secret.manage"] });
    await expect(page.getByRole("switch")).toBeDisabled();
  });

  test("does not offer an unsupported route", async ({ page }) => {
    await open(page, { supported: false });
    await expect(page.getByRole("switch")).toBeDisabled();
  });

  test("offers an explicit restore after a failed transition and shows SharePoint reconnect guidance", async ({ page }) => {
    const requests = await open(page, { provider: "sharepoint", status: "ERROR", desired: true, lastVerified: false, reconnectRequired: true });
    await expect(page.getByRole("alert").filter({ hasText: "Reconnect SharePoint" })).toBeVisible();
    await page.getByRole("button", { name: "Restore previous mode", exact: true }).click();
    await page.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();
    expect(requests).toEqual([{ isolated: false, restart: true }]);
  });

  test("shows the platform Firecrawl source as an independent isolation control", async ({ page }) => {
    const requests = await open(page, { provider: "firecrawl", source: "platform_default" });
    await expect(page.getByText("Uses the operator's default Firecrawl credential.")).toBeVisible();
    await page.getByRole("switch", { name: "Platform Firecrawl isolation" }).click();
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply", exact: true }).click();
    expect(requests).toEqual([{ isolated: true, restart: false }]);
  });

  test("shows slow startup as unverified and refreshes when the runtime becomes ready", async ({ page }) => {
    await open(page, { status: "RUNNING", desired: true, provisioning: true });
    await expect(page.getByText("Waiting for startup.", { exact: false })).toBeVisible();
    await expect(page.getByText("Current runtime: isolated.", { exact: false })).toBeVisible();
    await expect(page.getByText("Waiting for startup.", { exact: false })).not.toBeVisible();
  });
});
