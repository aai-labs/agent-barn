import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentAddonsSection } from "../pages/agent-addons-page.po";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import { AgentAddonDataSupport, mockAgentAddon } from "../pages/data-support/agent-addon-data-support.po";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const OWNER_ACTIONS = [...mockAgentAllowedActions, "agent.addon.manage"];

const PENDING = mockAgentAddon();
const APPROVED = mockAgentAddon({
  id: "55555555-5555-4555-8555-000000000002",
  kind: "git",
  name: "toolkit",
  spec: { url: "https://github.com/example/toolkit.git", commit: "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d" },
  reason: "Shared drawing templates.",
  state: "APPROVED",
  decided_at: "2026-10-22T09:00:00Z",
});
const REJECTED = mockAgentAddon({
  id: "55555555-5555-4555-8555-000000000003",
  kind: "command",
  name: "fonts",
  spec: { command: "curl -fsSL https://example.com/fonts.sh | bash" },
  reason: "Render reports with our fonts.",
  state: "REJECTED",
  rejection_reason: "Pin the script to a release and checksum it.",
  decided_at: "2026-10-22T10:00:00Z",
});

async function openAddons(page: Page, agent: Record<string, unknown>) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({ body: agent });
  await data.agents.interceptGetAgentConfigurationRequest();
  await data.agents.interceptGetTemplatesRequest();
  await data.agents.interceptGetTemplateVersionsRequest();
}

test.describe("An agent's add-ons", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("an owner sees each add-on with its state, pin, why and any rejection reason", async ({ page }) => {
    await openAddons(page, { ...mockAgent, allowed_actions: OWNER_ACTIONS });
    await new AgentAddonDataSupport(page).interceptAgentAddons({ addons: [PENDING, APPROVED, REJECTED] });
    const addons = new AgentAddonsSection(page);

    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(addons.addon("humanize")).toContainText("Pending review");
    await expect(addons.addon("humanize")).toContainText("humanize==4.12.3");
    await expect(addons.addon("humanize")).toContainText(PENDING.reason);
    await expect(addons.addon("toolkit")).toContainText("Approved");
    await expect(addons.addon("toolkit")).toContainText("@ 7fd1a60b01f91b314f59955a4e4d4e80d8edf11d");
    await expect(addons.addon("fonts")).toContainText("Rejected");
    await expect(addons.addon("fonts")).toContainText("Not approved: Pin the script to a release and checksum it.");
    await expect(addons.addon("humanize").getByRole("button", { name: "Withdraw" })).toBeVisible();
    await expect(addons.addon("toolkit").getByRole("button", { name: "Withdraw" })).toHaveCount(0);
  });

  test("an owner requests a pinned Python package, saying why", async ({ page }) => {
    await openAddons(page, { ...mockAgent, allowed_actions: OWNER_ACTIONS });
    const { requests } = await new AgentAddonDataSupport(page).interceptAgentAddons();
    const addons = new AgentAddonsSection(page);
    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await addons.requestButton().click();
    await addons.fill("Package", "humanize");
    await addons.fill("Version", "4.12.3");
    await expect(addons.dialog().getByRole("button", { name: "Request add-on" })).toBeDisabled();
    await addons.fill("Why does the agent need it?", "Formats numbers and dates in reports.");
    await addons.submitRequest();

    await expect(addons.dialog()).toHaveCount(0);
    await expect(addons.addon("humanize")).toContainText("Pending review");
    expect(requests).toEqual([
      { kind: "pip", name: "humanize", version: "4.12.3", reason: "Formats numbers and dates in reports." },
    ]);
  });

  test("the request dialog asks each kind for its own pin and offers only the runtime's kinds", async ({ page }) => {
    await openAddons(page, { ...mockAgent, agent_type: "hermes", allowed_actions: OWNER_ACTIONS });
    const { requests } = await new AgentAddonDataSupport(page).interceptAgentAddons({
      availableKinds: ["pip", "git", "binary", "command"],
    });
    const addons = new AgentAddonsSection(page);
    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await addons.requestButton().click();
    await addons.dialog().getByRole("combobox", { name: "Kind" }).click();
    await expect(page.getByRole("option", { name: "npm package" })).toHaveCount(0);
    await page.getByRole("option", { name: "Binary download", exact: true }).click();
    await addons.fill("Name", "drawtool");
    await addons.fill("Download URL", "https://example.com/drawtool");
    await addons.fill("SHA-256", "a".repeat(64));
    await addons.fill("Why does the agent need it?", "Converts files between formats.");
    await addons.submitRequest();

    await expect(addons.addon("drawtool")).toBeVisible();
    expect(requests).toEqual([
      {
        kind: "binary",
        name: "drawtool",
        url: "https://example.com/drawtool",
        sha256: "a".repeat(64),
        reason: "Converts files between formats.",
      },
    ]);
  });

  test("an owner withdraws a pending request after confirming", async ({ page }) => {
    await openAddons(page, { ...mockAgent, allowed_actions: OWNER_ACTIONS });
    const { withdrawals } = await new AgentAddonDataSupport(page).interceptAgentAddons({ addons: [PENDING] });
    const addons = new AgentAddonsSection(page);
    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await addons.withdraw("humanize");

    await expect(addons.addon("humanize")).toContainText("Withdrawn");
    expect(withdrawals).toEqual([PENDING.id]);
  });

  test("a running agent whose approved add-ons changed says they apply on restart", async ({ page }) => {
    await openAddons(page, { ...mockAgent, pending_addons: true, allowed_actions: OWNER_ACTIONS });
    await new AgentAddonDataSupport(page).interceptAgentAddons({ addons: [APPROVED] });
    const addons = new AgentAddonsSection(page);

    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(addons.pendingNote()).toContainText("Pending: applies on restart");
    await expect(addons.pendingNote().getByRole("button", { name: "Restart" })).toBeEnabled();
  });

  test("nothing is pending while the running agent has the approved set", async ({ page }) => {
    await openAddons(page, { ...mockAgent, pending_addons: false, allowed_actions: OWNER_ACTIONS });
    await new AgentAddonDataSupport(page).interceptAgentAddons({ addons: [APPROVED] });
    const addons = new AgentAddonsSection(page);

    await addons.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(addons.addon("toolkit")).toBeVisible();
    await expect(addons.pendingNote()).toHaveCount(0);
  });

  test("a member with agent access is not offered the add-ons section", async ({ page }) => {
    await openAddons(page, { ...mockAgent, allowed_actions: mockAgentAllowedActions });
    await new AgentAddonDataSupport(page).interceptAgentAddons({ addons: [PENDING] });
    const configuration = new AgentConfigurationPage(page);

    await new AgentAddonsSection(page).goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(configuration.profileHeading()).toBeVisible();
    await expect(configuration.sectionLink("Add-ons")).toHaveCount(0);
    await expect(page.getByTestId("agent-addons-settings")).toHaveCount(0);
  });
});
