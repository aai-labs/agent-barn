import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const SALES_ID = "66666666-6666-4666-8666-666666666661";
const LAWYER_ID = "66666666-6666-4666-8666-666666666662";
const NEW_BOT_ID = "66666666-6666-4666-8666-666666666663";

const parent = { ...mockAgent, name: "Front Desk", agent_type: "hermes", status: "STOPPED", parent_agent_id: null };
const bot = (id: string, name: string) => ({ ...parent, id, name, parent_agent_id: MOCK_AGENT_ID });
const sales = bot(SALES_ID, "Sales");
const lawyer = bot(LAWYER_ID, "Lawyer");

async function setUp(page: Page, agent: typeof parent = parent, bots: unknown[] = [sales, lawyer]) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentsRequest({ body: { items: [agent], page: 1, page_size: 15, total: 1 } });
  await data.agents.interceptGetAgentRequest({ body: agent });
  await data.agents.interceptGetAgentRequest({ agentId: SALES_ID, body: sales });
  await data.agents.interceptGetAgentRequest({ agentId: NEW_BOT_ID, body: bot(NEW_BOT_ID, "Researcher") });
  await data.agents.interceptGetAgentHealthRequest();
  await data.agents.interceptGetAgentHealthRequest({ agentId: SALES_ID });
  await data.agents.interceptGetAgentConfigurationRequest();
  await data.agents.interceptGetTemplatesRequest();
  await data.agents.interceptGetModelsRequest();
  await data.agents.interceptNameSuggestionRequest();
  await data.agents.interceptGetConversationChannelsRequest();
  await data.costs.interceptAgentCosts(MOCK_AGENT_ID);
  await data.costs.interceptAgentCosts(SALES_ID);
  const created: unknown[] = [];
  await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/bots`, async (route) => {
    if (route.request().method() === "POST") {
      created.push(route.request().postDataJSON());
      await route.fulfill({ status: 201, json: bot(NEW_BOT_ID, "Researcher") });
      return;
    }
    await route.fulfill({ json: bots });
  });
  return { data, created };
}

const goto = (page: Page, agentId = MOCK_AGENT_ID, search = "") =>
  page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}${search}`);
const switcher = (page: Page) => page.getByRole("button", { name: /^Switch bot/ });

async function openNewBot(page: Page) {
  await switcher(page).click();
  await page.getByRole("menuitem", { name: "New bot" }).click();
  await expect(page.getByRole("heading", { name: "Add a bot" })).toBeVisible();
  await page.getByLabel("Bot name").fill("Researcher");
  await page.getByRole("combobox", { name: "Template", exact: true }).click();
  await page.getByRole("option", { name: "General Purpose · v1" }).click();
}

test.describe("Agent Bots switcher", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("lists the parent as main, then its bots", async ({ page }) => {
    await setUp(page);
    await goto(page);

    await expect(switcher(page)).toContainText("Main");
    await switcher(page).click();

    const items = page.getByRole("menuitem");
    await expect(items.filter({ hasText: "Front Desk" })).toContainText("main");
    await expect(items.filter({ hasText: "Sales" })).toBeVisible();
    await expect(items.filter({ hasText: "Lawyer" })).toBeVisible();
  });

  test("switching to a bot keeps the current tab", async ({ page }) => {
    await setUp(page);
    await goto(page, MOCK_AGENT_ID, "?tab=activity");

    await switcher(page).click();
    await page.getByRole("menuitem").filter({ hasText: "Sales" }).click();

    await expect(page).toHaveURL(new RegExp(`/agents/${SALES_ID}\\?tab=activity`));
  });

  test("on a bot the path shows its parent and the bot", async ({ page }) => {
    await setUp(page);
    await goto(page, SALES_ID);

    await expect(page.getByRole("button", { name: "Switch agent. Current: Front Desk" })).toBeVisible();
    await expect(switcher(page)).toContainText("Sales");
  });

  test("an OpenClaw agent has no bot switcher", async ({ page }) => {
    await setUp(page, { ...parent, agent_type: "openclaw" }, []);
    await goto(page);

    await expect(page.getByRole("button", { name: /^Switch agent/ })).toBeVisible();
    await expect(switcher(page)).toHaveCount(0);
  });

  test("someone who cannot edit the parent is not offered a new bot", async ({ page }) => {
    await setUp(page, { ...parent, allowed_actions: ["agent.read"] });
    await goto(page);

    await switcher(page).click();

    await expect(page.getByRole("menuitem", { name: "New bot" })).toHaveCount(0);
  });

  test("a parent with five bots cannot add another", async ({ page }) => {
    const five = [1, 2, 3, 4, 5].map((n) => bot(`66666666-6666-4666-8666-66666666670${n}`, `Bot ${n}`));
    await setUp(page, parent, five);
    await goto(page);

    await switcher(page).click();

    await expect(page.getByRole("menuitem", { name: /New bot/ })).toHaveAttribute("aria-disabled", "true");
  });
});

test.describe("New bot dialog", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("adds a bot to a stopped parent without restarting it", async ({ page }) => {
    const { created } = await setUp(page);
    await goto(page);

    await openNewBot(page);
    await expect(page.getByRole("radiogroup", { name: "Runtime" })).toHaveCount(0);
    await page.getByRole("button", { name: "Add bot" }).click();

    await expect(page).toHaveURL(new RegExp(`/agents/${NEW_BOT_ID}`));
    expect(created[0]).toMatchObject({ name: "Researcher", template_key: expect.any(String), approval_mode: "auto" });
    expect(created[0]).not.toHaveProperty("agent_type");
    expect(created[0]).not.toHaveProperty("file_sync_enabled");
  });

  test("adding a bot to a running parent stops and restarts it", async ({ page }) => {
    const running = { ...parent, status: "RUNNING" };
    const { data, created } = await setUp(page, running);
    await data.agents.interceptStopAgentRequest({ body: { ...running, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ body: running });
    await goto(page);
    const stop = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/stop`);
    const start = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/start`);

    await openNewBot(page);
    await page.getByRole("button", { name: "Add & Restart" }).click();

    await stop;
    await start;
    await expect(page).toHaveURL(new RegExp(`/agents/${NEW_BOT_ID}`));
    expect(created).toHaveLength(1);
  });

  test("a running parent needs permission to restart", async ({ page }) => {
    await setUp(page, { ...parent, status: "RUNNING", allowed_actions: ["agent.read", "agent.update"] });
    await goto(page);

    await openNewBot(page);

    await expect(page.getByRole("button", { name: "Add & Restart" })).toBeDisabled();
    await expect(page.getByText("You need permission to restart Front Desk.")).toBeVisible();
  });

  test("a manual parent makes the new bot manual", async ({ page }) => {
    const { created } = await setUp(page, { ...parent, approval_mode: "manual" });
    await goto(page);

    await openNewBot(page);
    await expect(page.getByRole("combobox", { name: "Command approval" })).toBeDisabled();
    await page.getByRole("button", { name: "Add bot" }).click();

    await expect(page).toHaveURL(new RegExp(`/agents/${NEW_BOT_ID}`));
    expect(created[0]).toMatchObject({ approval_mode: "manual" });
  });
});
