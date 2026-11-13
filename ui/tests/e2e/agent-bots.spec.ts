import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAssignedMember,
  mockShareSettingsAll,
  mockShareSettingsRestricted,
} from "../pages/data-support/agent-data-support.po";
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

test.describe("Bot pages", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const running = { ...parent, status: "RUNNING" };
  const runningSales = { ...sales, status: "RUNNING" };
  const agentHref = (id: string, suffix = "") => `/dashboard/${TEST_ORG_ID}/agents/${id}${suffix}`;
  const panel = (page: Page, name: string) => page.getByRole("navigation", { name, exact: true });
  const lifecycle = (page: Page) => page.getByTestId("agent-lifecycle-menu");
  const POD_LINKS = [
    ["Logs", "?tab=logs"],
    ["File sync", "?tab=file-sync"],
    ["Resource usage", "?tab=resource-usage"],
    ["Restore points", "/configuration?section=restore"],
    ["Size", "/configuration?section=profile"],
  ];

  test("a bot's sections are its own and pod-wide pages link to the parent", async ({ page }) => {
    await setUp(page);
    await goto(page, SALES_ID);

    const nav = panel(page, "Sales");
    await expect(nav.getByRole("link", { name: "Tool calls" })).toHaveAttribute(
      "href",
      agentHref(SALES_ID, "?tab=tool-calls"),
    );
    await expect(nav.getByText("Shared by every bot")).toBeVisible();
    for (const [name, suffix] of POD_LINKS) {
      await expect(nav.getByRole("link", { name, exact: true })).toHaveAttribute(
        "href",
        agentHref(MOCK_AGENT_ID, suffix),
      );
    }
  });

  test("a Hermes parent keeps the same pod-wide group, on itself", async ({ page }) => {
    await setUp(page);
    await goto(page);

    const nav = panel(page, "Front Desk");
    await expect(nav.getByText("Shared by every bot")).toBeVisible();
    await expect(nav.getByRole("link", { name: "Logs", exact: true })).toHaveAttribute(
      "href",
      agentHref(MOCK_AGENT_ID, "?tab=logs"),
    );
  });

  test("an OpenClaw agent has no pod-wide group", async ({ page }) => {
    await setUp(page, { ...parent, agent_type: "openclaw" }, []);
    await goto(page);

    const nav = panel(page, "Front Desk");
    await expect(nav.getByRole("link", { name: "Logs", exact: true })).toBeVisible();
    await expect(nav.getByText("Shared by every bot")).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Restore points" })).toHaveCount(0);
  });

  test("a pod-wide tab opened on a bot falls back to its Overview", async ({ page }) => {
    await setUp(page);
    await goto(page, SALES_ID, "?tab=logs");

    await expect(panel(page, "Sales").getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  });

  test("a bot's Activity does not ask for the pod's diagnostics", async ({ page }) => {
    await setUp(page);
    const asked: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes(`/agents/${SALES_ID}/diagnostics`)) asked.push(request.url());
    });
    await goto(page, SALES_ID, "?tab=activity");

    await expect(panel(page, "Sales").getByRole("link", { name: "Activity" })).toHaveAttribute("aria-current", "page");
    await page.waitForTimeout(1_000);
    expect(asked).toEqual([]);
  });

  test("Pause on a bot stops its parent", async ({ page }) => {
    const { data } = await setUp(page, running);
    await data.agents.interceptGetAgentRequest({ agentId: SALES_ID, body: runningSales });
    await data.agents.interceptStopAgentRequest({ body: { ...running, status: "STOPPED" } });
    await goto(page, SALES_ID);
    const stop = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/stop`);

    await lifecycle(page).getByRole("button", { name: "Pause" }).click();

    await stop;
  });

  test("a bot offers no lifecycle actions without restart rights on its parent", async ({ page }) => {
    await setUp(page, { ...parent, allowed_actions: ["agent.read", "activity.read"] });
    await goto(page, SALES_ID);

    await expect(page.getByTestId("agent-runtime-chip")).toBeVisible();
    await expect(lifecycle(page)).toHaveCount(0);
  });

  test("Apply & Restart on a bot restarts its parent", async ({ page }) => {
    const { data } = await setUp(page, running);
    await data.agents.interceptGetAgentRequest({ agentId: SALES_ID, body: runningSales });
    await data.agents.interceptGetAgentConfigurationRequest({ agentId: SALES_ID });
    await data.agents.interceptStopAgentRequest({ body: { ...running, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ body: running });
    await data.agents.interceptUpdateAgentRequest({ agentId: SALES_ID, body: runningSales });
    const onBot: string[] = [];
    page.on("request", (request) => {
      if (/\/agents\/[^/]+\/(stop|start)$/.test(request.url()) && request.url().includes(SALES_ID)) {
        onBot.push(request.url());
      }
    });
    await goto(page, SALES_ID, "/configuration?section=profile");
    const stop = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/stop`);
    const save = page.waitForRequest(
      (request) => request.method() === "PATCH" && request.url().endsWith(`/agents/${SALES_ID}`),
    );
    const start = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/start`);

    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Agent name").fill("Sales desk");
    const footer = page.locator('section[aria-label="Profile"] footer');
    await footer.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();

    await stop;
    expect((await save).postDataJSON()).not.toHaveProperty("max_turns");
    await start;
    expect(onBot).toEqual([]);
  });

  test("saving credentials on a running bot restarts its parent", async ({ page }) => {
    const { data } = await setUp(page, running);
    await data.agents.interceptGetAgentRequest({
      agentId: SALES_ID,
      body: {
        ...runningSales,
        secrets: [{ provider: "github", secret_name: "GitHub credential", source: "agent_secret" }],
      },
    });
    await data.agents.interceptGetAgentConfigurationRequest({ agentId: SALES_ID });
    await data.agents.interceptGetCustomApiConnectionsRequest(SALES_ID);
    await data.agents.interceptStopAgentRequest({ body: { ...running, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ body: running });
    await data.agents.interceptUpdateAgentRequest({ agentId: SALES_ID, body: runningSales });
    await goto(page, SALES_ID, "/configuration?section=keys");
    const stop = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/stop`);
    const save = page.waitForRequest(
      (request) => request.method() === "PATCH" && request.url().endsWith(`/agents/${SALES_ID}`),
    );
    const start = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/start`);

    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.locator("summary").filter({ hasText: "GitHub" }).click();
    await page.getByRole("button", { name: "Replace credential" }).click();
    await page.getByPlaceholder("github_pat_… or ghp_…").fill("fixture-token");
    await page.getByPlaceholder("owner-or-org").fill("fixture-org");
    await page.getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();

    await stop;
    expect((await save).postDataJSON()).toMatchObject({ restart: false });
    await start;
  });

  test("restarting for a pending model on a bot restarts its parent", async ({ page }) => {
    const { data } = await setUp(page, running);
    await data.agents.interceptGetAgentRequest({
      agentId: SALES_ID,
      body: { ...runningSales, pending_model: "openai/gpt-next" },
    });
    await data.agents.interceptStopAgentRequest({ body: { ...running, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest({ body: running });
    await goto(page, SALES_ID);
    const stop = page.waitForRequest(`**/agents/${MOCK_AGENT_ID}/stop`);

    await page.getByTestId("agent-pending-model-restart").click();

    await stop;
  });

  test("a bot's settings leave out pod-wide controls and the turn limit", async ({ page }) => {
    const { data } = await setUp(page);
    await data.agents.interceptGetAgentConfigurationRequest({ agentId: SALES_ID });
    await goto(page, SALES_ID, "/configuration?section=profile");

    await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible();
    await expect(panel(page, "Sales").getByRole("link", { name: "Restore points" })).toHaveCount(0);
    await expect(page.getByTestId("agent-size-tile")).toHaveCount(0);

    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await expect(page.getByLabel("Agent name")).toBeVisible();
    await expect(page.getByLabel("Turn limit")).toHaveCount(0);
  });

  test("the switcher shows a bot the pod is not serving", async ({ page }) => {
    const { data } = await setUp(page, running, [runningSales, lawyer]);
    await data.agents.interceptGetAgentHealthRequest({
      agentId: SALES_ID,
      body: { status: "error", reason: "This Bot could not start." },
    });
    await goto(page);

    await switcher(page).click();

    await expect(
      page.getByRole("menuitem").filter({ hasText: "Sales" }).getByRole("img", { name: "Disconnected" }),
    ).toBeVisible();
  });
});

test.describe("Home with bots", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const openHome = async (page: Page, bots: unknown[]) => {
    const { data } = await setUp(page, parent, bots);
    await data.organizations.interceptGetOrganizationLlmBudget();
    await page.goto(`/dashboard/${TEST_ORG_ID}`);
    return page.getByRole("link", { name: "View Front Desk" });
  };

  test("a parent's card counts its bots and flags one needing attention", async ({ page }) => {
    const card = await openHome(page, [sales, { ...lawyer, status: "ERROR" }]);

    await expect(card).toContainText("2 bots");
    await expect(card).toContainText("1 needs attention");
  });

  test("one healthy bot reads in the singular with no flag", async ({ page }) => {
    const card = await openHome(page, [sales]);

    await expect(card).toContainText("1 bot");
    await expect(card).not.toContainText("needs attention");
  });

  test("a parent with no bots shows no count", async ({ page }) => {
    const card = await openHome(page, []);

    await expect(card).toBeVisible();
    await expect(card).not.toContainText(/\d bots?/);
  });
});

test.describe("Sharing and trust", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const TRUST_WARNING = "Bots in one Agent can read each other's credentials.";
  const ADA = {
    user_id: mockAssignedMember.user_id,
    email: mockAssignedMember.email,
    full_name: mockAssignedMember.full_name,
    role: "MEMBER",
    is_pending: false,
  };
  const GRACE = {
    user_id: "99999999-9999-4999-8999-999999999999",
    email: "grace@example.com",
    full_name: "Grace Hopper",
    role: "MEMBER",
    is_pending: false,
  };
  const NO_SHARES = { general_access: { role: null }, assignments: [] };

  async function openBotShare(
    page: Page,
    { parentShare = mockShareSettingsRestricted as unknown, agent = parent } = {},
  ) {
    const { data } = await setUp(page, agent);
    await data.agents.interceptGetShareRolesRequest();
    await data.agents.interceptGetAgentShareRequest({ body: parentShare });
    await data.agents.interceptGetAgentShareRequest({ agentId: SALES_ID, body: NO_SHARES });
    await data.organizations.interceptGetMembers({ members: [ADA, GRACE] });
    await goto(page, SALES_ID);
    await page.getByRole("button", { name: "Share", exact: true }).click();
    return page.getByRole("dialog");
  }

  async function searchMembers(page: Page) {
    await page.getByLabel("Search Members to grant access").fill("example");
    await expect(page.getByRole("dialog").getByText(GRACE.email)).toBeVisible();
  }

  test("the new bot dialog warns that bots share a trust boundary", async ({ page }) => {
    await setUp(page);
    await goto(page);

    await openNewBot(page);

    await expect(page.getByText(TRUST_WARNING)).toBeVisible();
  });

  test("the bot switcher warns that bots share a trust boundary", async ({ page }) => {
    await setUp(page);
    await goto(page);

    await switcher(page).click();

    await expect(page.getByRole("menu").getByText(TRUST_WARNING)).toBeVisible();
  });

  test("sharing a bot warns that bots share a trust boundary", async ({ page }) => {
    const dialog = await openBotShare(page);

    await expect(dialog.getByText(TRUST_WARNING)).toBeVisible();
  });

  test("sharing a parent shows no bot warning", async ({ page }) => {
    const { data } = await setUp(page);
    await data.agents.interceptGetShareRolesRequest();
    await data.agents.interceptGetAgentShareRequest();
    await goto(page);

    await page.getByRole("button", { name: "Share", exact: true }).click();

    await expect(page.getByRole("heading", { name: "Share Front Desk" })).toBeVisible();
    await expect(page.getByRole("dialog").getByText(TRUST_WARNING)).toHaveCount(0);
  });

  test("a bot can be shared only with members who can open its parent", async ({ page }) => {
    const dialog = await openBotShare(page);

    await searchMembers(page);

    await expect(dialog.getByRole("button", { name: `Add ${ADA.email}` })).toBeVisible();
    await expect(dialog.getByRole("button", { name: `Add ${GRACE.email}` })).toHaveCount(0);
    await expect(dialog.getByText("Needs access to Front Desk first")).toBeVisible();
  });

  test("a parent open to the whole organization lets anyone be added", async ({ page }) => {
    const dialog = await openBotShare(page, { parentShare: mockShareSettingsAll });

    await searchMembers(page);

    await expect(dialog.getByRole("button", { name: `Add ${GRACE.email}` })).toBeVisible();
  });

  test("without access management on the parent, the server decides", async ({ page }) => {
    const asked: string[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith(`/agents/${MOCK_AGENT_ID}/share`)) asked.push(request.url());
    });
    const dialog = await openBotShare(page, {
      agent: { ...parent, allowed_actions: ["agent.read", "activity.read"] },
    });

    await searchMembers(page);

    await expect(dialog.getByRole("button", { name: `Add ${GRACE.email}` })).toBeVisible();
    expect(asked).toEqual([]);
  });

  test("general access on a bot needs general access on its parent", async ({ page }) => {
    const dialog = await openBotShare(page);

    await expect(dialog.getByRole("option", { name: "All Organization Members" })).toBeDisabled();
    await expect(dialog.getByText("Give Front Desk General access first.")).toBeVisible();
  });

  test("a parent with general access lets its bot have it too", async ({ page }) => {
    const dialog = await openBotShare(page, { parentShare: mockShareSettingsAll });

    await expect(dialog.getByRole("option", { name: "All Organization Members" })).toBeEnabled();
    await expect(dialog.getByText("Give Front Desk General access first.")).toHaveCount(0);
  });
});
