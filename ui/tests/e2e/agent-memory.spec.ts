import { expect, test, type Page } from "@playwright/test";

import { ORG_A_ID, ORG_B_ID } from "../pages/data-support/organization-data-support.po";
import { TEST_ORG_ID } from "../constants";
import UserContext from "../fixtures/user-context.json";
import { AgentMemoryPage } from "../pages/agent-memory-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import {
  MOCK_READER_AGENT_ID,
  mockMemoryGrant,
  mockMemoryItems,
} from "../pages/data-support/agent-memory-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const OWNER_ACTIONS = [...mockAgentAllowedActions, "agent.memory.manage"];

function memberContext() {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({
      ...membership,
      role: "MEMBER",
    })),
  };
}

/** Platform administrators see admin settings, but only an Owner or Admin holds memory.access.manage. */
function platformAdminMemberContext() {
  return { ...memberContext(), is_platform_admin: true };
}

function twoOrganizationContext() {
  const [first] = UserContext.organization_users;
  const globex = {
    ...first,
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    organization_id: ORG_B_ID,
    organization: { ...first.organization, id: ORG_B_ID, name: "Globex" },
  };
  return { ...UserContext, organization_users: [first, globex] };
}

async function signIn(page: Page, userContext?: unknown) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext });
  await data.users.interceptGetOrganizationsRequest();
  return data;
}

test.describe("Agent Memory setting", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  async function open(page: Page, allowedActions: string[], enabled = false) {
    const data = await signIn(page);
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetAgentHealthRequest();
    const setting = await data.agentMemory.interceptAgentMemorySetting({
      agent: { ...mockAgent, allowed_actions: allowedActions },
      enabled,
    });
    await new AgentMemoryPage(page).gotoMemorySettings();
    return { data, setting, memory: new AgentMemoryPage(page) };
  }

  test("turns memory on, saying what it does and does not do", async ({ page }) => {
    const { setting, memory } = await open(page, OWNER_ACTIONS);

    await expect(memory.settingsSection()).toContainText("Off");
    await expect(memory.settingsSection()).toContainText("never replaces it");
    await expect(memory.settingsSection()).toContainText("restart it");

    await memory.editSetting();
    await memory.toggleSetting();
    await memory.saveSetting();

    await expect(memory.settingsSection()).toContainText("On");
    expect(setting.requests.map((request) => request.body)).toEqual([{ enabled: true }]);
  });

  test("turns memory off and states that saved memories are kept", async ({ page }) => {
    const { setting, memory } = await open(page, OWNER_ACTIONS, true);

    await expect(memory.settingsSection()).toContainText("On");
    await memory.editSetting();
    await memory.toggleSetting();
    await memory.settingsSection().getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("dialog")).toContainText("Memories already saved are kept");
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();

    await expect(memory.settingsSection()).toContainText("Off");
    expect(setting.requests.map((request) => request.body)).toEqual([{ enabled: false }]);
  });

  test("is read-only without the memory-management permission", async ({ page }) => {
    const { memory } = await open(page, mockAgentAllowedActions, true);

    await expect(memory.settingsSection()).toContainText("On");
    await expect(memory.settingsSection()).toContainText("Only people who can manage");
    await expect(memory.settingsSection().getByRole("button", { name: "Edit" })).toHaveCount(0);
  });

  test("shows the server's refusal inline and keeps the displayed setting", async ({ page }) => {
    const data = await signIn(page);
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agentMemory.interceptAgentMemorySetting({
      agent: { ...mockAgent, allowed_actions: OWNER_ACTIONS },
      putStatus: 403,
      putDetail: "You don't have permission to manage this Agent's memory.",
    });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemorySettings();

    await memory.editSetting();
    await memory.toggleSetting();
    await memory.saveSetting();

    await expect(memory.settingsSection().getByRole("alert")).toContainText("don't have permission");
    await expect(memory.settingsSection()).toContainText("Off");
  });
});

test.describe("Memory access settings", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("lists, creates, rejects duplicates of, and revokes grants", async ({ page }) => {
    const data = await signIn(page);
    await data.agentMemory.interceptAgentOptions();
    const grants = await data.agentMemory.interceptMemoryGrants({ grants: [mockMemoryGrant] });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    await expect(memory.grantsSection()).toContainText("Billing can read Triage's private memories");

    await memory.chooseReader("Billing");
    await memory.chooseSource("Organization Memory");
    await memory.grantButton().click();
    await expect(memory.grantsSection()).toContainText("Billing can read and write Organization Memory");
    expect(grants.requests.find((request) => request.method === "POST")?.body).toEqual({
      agent_id: MOCK_READER_AGENT_ID,
      source_agent_id: null,
    });

    // The same pair again is stopped before it is sent, and the server's 409 is shown if raced.
    await memory.chooseReader("Billing");
    await memory.chooseSource("Organization Memory");
    await expect(page.getByText("That Agent already has this access.")).toBeVisible();
    await expect(memory.grantButton()).toBeDisabled();

    await memory.revoke("Billing can read Triage's private memories");
    await expect(memory.grantsSection()).not.toContainText("Triage's private memories");
    expect(grants.requests.filter((request) => request.method === "DELETE")).toHaveLength(1);
  });

  test("never offers an Agent its own private memories", async ({ page }) => {
    const data = await signIn(page);
    await data.agentMemory.interceptAgentOptions();
    await data.agentMemory.interceptMemoryGrants();
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    await memory.chooseReader("Billing");
    await memory.openSourceChoices();

    await expect(memory.sourceOptions().filter({ hasText: /^Billing$/ })).toHaveCount(0);
    await expect(memory.sourceOptions().filter({ hasText: /^Triage$/ })).toHaveCount(1);
    await expect(memory.sourceOptions().filter({ hasText: /^Organization Memory$/ })).toHaveCount(1);
  });

  test("shows the server's error when creating a grant is refused", async ({ page }) => {
    const data = await signIn(page);
    await data.agentMemory.interceptAgentOptions();
    const grants = await data.agentMemory.interceptMemoryGrants();
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    // Another admin created the same grant after this page loaded.
    grants.unlisted.push({ ...mockMemoryGrant, source_agent_id: null, source_agent_name: null });
    await memory.chooseReader("Billing");
    await memory.chooseSource("Organization Memory");
    await memory.grantButton().click();

    await expect(memory.grantForm().getByRole("alert")).toContainText("already has that memory grant");
  });

  test("shows an inline error with retry when grants cannot be loaded", async ({ page }) => {
    const data = await signIn(page);
    await data.agentMemory.interceptAgentOptions();
    await data.agentMemory.interceptMemoryGrants({ listStatus: 503 });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    await expect(page.getByText("We couldn't load memory access")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });

  test("is hidden from Members and issues no grant requests for them", async ({ page }) => {
    const data = await signIn(page, memberContext());
    await data.agentMemory.interceptAgentOptions();
    const grants = await data.agentMemory.interceptMemoryGrants({ grants: [mockMemoryGrant] });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    await expect(page.getByRole("button", { name: "Memory access" })).toHaveCount(0);
    await expect(page.getByText("can read Triage")).toHaveCount(0);
    expect(grants.requests).toHaveLength(0);
  });

  test("is hidden from a platform administrator who is only a Member of the Organization", async ({ page }) => {
    const data = await signIn(page, platformAdminMemberContext());
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptAgentSettings();
    await data.agents.interceptGetModelsRequest();
    await data.agentMemory.interceptAgentOptions();
    const grants = await data.agentMemory.interceptMemoryGrants({ grants: [mockMemoryGrant] });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess();

    await expect(page.getByRole("button", { name: "Shared Credentials" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Memory access" })).toHaveCount(0);
    expect(grants.requests).toHaveLength(0);
  });

  test("does not show one organization's grants under another", async ({ page }) => {
    const data = await signIn(page, twoOrganizationContext());
    await data.organizations.interceptGetOrganization();
    await data.agentMemory.interceptAgentOptions({ organizationId: ORG_A_ID });
    await data.agentMemory.interceptAgentOptions({ organizationId: ORG_B_ID, agents: [] });
    await data.agentMemory.interceptMemoryGrants({ organizationId: ORG_A_ID, grants: [mockMemoryGrant] });
    const globex = await data.agentMemory.interceptMemoryGrants({ organizationId: ORG_B_ID });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryAccess(ORG_A_ID);
    await expect(memory.grantsSection()).toContainText("Billing can read Triage's private memories");

    const switcher = page.locator('button[aria-haspopup="listbox"]');
    await switcher.click();
    await page.getByRole("listbox").getByRole("option", { name: /globex/i }).click();
    await expect(page).toHaveURL(new RegExp(`/dashboard/${ORG_B_ID}`));
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await page.getByRole("button", { name: "Memory access" }).click();

    await expect(page.getByText("No memory access granted")).toBeVisible();
    await expect(page.getByText("Triage's private memories")).toHaveCount(0);
    expect(globex.requests.some((request) => request.method === "GET")).toBe(true);
  });
});

test.describe("Agent memory viewer", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  async function open(
    page: Page,
    {
      allowedActions = OWNER_ACTIONS,
      agent = {},
      items = mockMemoryItems,
      tab = "memory",
    }: {
      allowedActions?: string[];
      agent?: Record<string, unknown>;
      items?: Record<string, unknown>[];
      tab?: string;
    } = {},
  ) {
    const data = await signIn(page);
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: allowedActions, ...agent },
    });
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetConversationChannelsRequest();
    const mock = await data.agentMemory.interceptMemoryItems({ items });
    const memory = new AgentMemoryPage(page);
    await memory.gotoMemoryTab(MOCK_AGENT_ID, TEST_ORG_ID, tab);
    return { data, mock, memory };
  }

  test("lists saved memories read-only with their scope and date", async ({ page }) => {
    const { memory, mock } = await open(page);

    const viewer = memory.viewer();
    await expect(viewer).toContainText("Customers prefer invoices in euros.");
    await expect(viewer).toContainText("Fact");
    await expect(viewer).toContainText("Observation");
    await expect(viewer).toContainText("Private");
    await expect(viewer).toContainText("Shared · Organization Memory");
    await expect(viewer).toContainText("Mentioned");
    await expect(viewer).toContainText("No date recorded");
    await expect(viewer).toContainText("3 memories");
    // Viewing carries no way to change what is stored.
    await expect(viewer.getByRole("button", { name: /edit|delete|remove|forget/i })).toHaveCount(0);
    // The client names no bank or tag; the server derives both.
    const params = Object.fromEntries(mock.requests[0].url.searchParams);
    expect(Object.keys(params).sort()).toEqual(["page", "page_size"]);
  });

  test("renders memory text as plain text", async ({ page }) => {
    const { memory } = await open(page);

    await expect(memory.viewer()).toContainText("<img src=x onerror=alert(1)> **not bold**");
    await expect(memory.viewer().locator("img")).toHaveCount(0);
    await expect(memory.viewer().locator("strong")).toHaveCount(0);
  });

  test("searches and paginates through the server", async ({ page }) => {
    const items = Array.from({ length: 45 }, (_, index) => ({
      id: `p-${index}`,
      type: "world",
      text: `${index % 2 ? "Beta" : "Alpha"} note ${index}`,
      mentioned_at: "2026-10-01T12:30:00Z",
      shared: false,
    }));
    const { memory, mock } = await open(page, { items });

    await expect(memory.viewer()).toContainText("45 memories");
    await memory.nextPage();
    await expect(memory.viewer()).toContainText("Alpha note 20");
    expect(mock.requests.at(-1)?.url.searchParams.get("page")).toBe("2");

    await memory.search("beta");
    await expect(memory.viewer()).toContainText("22 memories");
    await expect(memory.viewer()).not.toContainText("Alpha note");
    const searched = mock.requests.at(-1)?.url.searchParams;
    expect(searched?.get("search")).toBe("beta");
    // A new search starts again from the first page.
    expect(searched?.get("page")).toBe("1");
  });

  test("shows an empty state, and still works for a stopped Agent with memory off", async ({ page }) => {
    const { memory } = await open(page, {
      agent: { status: "STOPPED", memory_enabled: false },
      items: [],
    });

    await expect(memory.viewer()).toContainText("Nothing saved yet");
    await expect(memory.viewer()).toContainText("Long-term memory is off");
  });

  test("shows an inline error and recovers on retry", async ({ page }) => {
    const { memory, mock } = await open(page);
    await expect(memory.viewer()).toContainText("Customers prefer invoices");

    mock.failWith(503);
    await memory.search("euros");
    await expect(page.getByText("We couldn't load this Agent's memories")).toBeVisible();

    mock.failWith(null);
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(memory.viewer()).toContainText("Customers prefer invoices");
  });

  test("shows a permission error from the server without exposing content", async ({ page }) => {
    const { memory, mock } = await open(page);
    mock.failWith(403);
    await memory.search("euros");

    await expect(page.getByText("We couldn't load this Agent's memories")).toBeVisible();
    await expect(memory.viewer()).not.toContainText("Customers prefer invoices");
  });

  test("is hidden and never queried without activity access, even with memory management", async ({ page }) => {
    const { memory, mock } = await open(page, {
      allowedActions: ["agent.read", "agent.memory.manage", "cost.read"],
      tab: "memory",
    });

    await expect(page.getByRole("button", { name: "Costs", exact: true })).toBeVisible();
    await expect(memory.tab()).toHaveCount(0);
    await expect(memory.viewer()).toHaveCount(0);
    expect(mock.requests).toHaveLength(0);
  });

  test("is not queried for a hidden tab before it is opened", async ({ page }) => {
    const { memory, mock } = await open(page, { tab: "about" });

    await expect(memory.tab()).toBeVisible();
    expect(mock.requests).toHaveLength(0);
    await memory.tab().click();
    await expect(memory.viewer()).toContainText("Customers prefer invoices");
    expect(mock.requests).toHaveLength(1);
  });
});
