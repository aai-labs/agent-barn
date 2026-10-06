import { expect, test, type Page } from "@playwright/test";

import { mockCommunicationConnection, mockCommunicationPlatforms } from "../fixtures/communication-connections";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

const CONNECTION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const TOKEN_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const LINK_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const DEEP_LINK = "https://t.me/AgentBarnTestBot?start=abcDEF123";
const CONNECTIONS = `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/connections`;
const LINKS = `${CONNECTIONS}/${CONNECTION_ID}/telegram-links`;
const TOKENS = `${CONNECTIONS}/${CONNECTION_ID}/telegram-link-tokens`;

const agentBarnTelegramPlatform = {
  key: "agentbarn_telegram",
  display_name: "Agent Barn Telegram",
  setup_hint: "Talk to this agent in Telegram without creating a bot.",
  schema_version: 1,
  capabilities: ["account_linking"],
  settings_schema: { type: "object", properties: {} },
  credentials_schema: { type: "object", properties: {} },
};

const linkedAccount = {
  id: LINK_ID,
  telegram_username: "jane_doe",
  linked_by_membership_id: "11111111-1111-4111-8111-111111111111",
  created_at: "2026-10-06T12:00:00Z",
};

function linkToken(status: "waiting" | "linked" | "expired", extra: Record<string, unknown> = {}) {
  return {
    id: TOKEN_ID,
    status,
    expires_at: "2026-10-06T12:10:00Z",
    telegram_username: status === "linked" ? "jane_doe" : null,
    ...extra,
  };
}

async function serve(page: Page, { enabled = true, links = [] as unknown[] } = {}) {
  await page.route("**/api/v1/organizations/*/communication-platforms", (route) =>
    route.fulfill({ json: [...mockCommunicationPlatforms, agentBarnTelegramPlatform] }),
  );
  await page.route(CONNECTIONS, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: [
        {
          ...mockCommunicationConnection,
          id: CONNECTION_ID,
          platform_key: "agentbarn_telegram",
          display_name: "Agent Barn Telegram",
          enabled,
          settings: {},
          external_identity: "@AgentBarnTestBot",
          last_error_code: null,
          last_error_message: null,
        },
      ],
    });
  });
  let current = [...links];
  await page.route(LINKS, (route) => route.fulfill({ json: current }));
  return {
    setLinks(next: unknown[]) {
      current = next;
    },
  };
}

async function openChannels(page: Page, allowedActions = mockAgentAllowedActions) {
  const dataSupport = new DataSupport(page);
  const agentDetailPage = new AgentDetailPage(page);
  await dataSupport.auth.interceptRefreshRequest();
  await dataSupport.users.interceptGetUserContextRequest();
  await dataSupport.users.interceptGetOrganizationsRequest();
  await dataSupport.agents.interceptGetAgentRequest({
    body: { ...mockAgent, status: "STOPPED", allowed_actions: allowedActions },
  });
  await dataSupport.agents.interceptGetAgentTemplateRequest();
  await dataSupport.agents.interceptGetConversationChannelsRequest();
  await dataSupport.agents.interceptGetTemplatesRequest();
  await dataSupport.agents.interceptGetAgentConfigurationRequest();
  await dataSupport.agents.interceptGetModelsRequest();
  await dataSupport.communicationConnections.interceptChannelsRequests({ agentId: MOCK_AGENT_ID });
  return agentDetailPage;
}

async function goToChannels(page: Page, agentDetailPage: AgentDetailPage) {
  await agentDetailPage.goto(MOCK_AGENT_ID);
  await agentDetailPage.configureButton().click();
  await agentDetailPage.channelsTab().click();
  await expect(page.getByText("Agent Barn Telegram").first()).toBeVisible();
}

test.describe("Agent Barn Telegram account linking", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("links a Telegram account through a one-time link", async ({ page }) => {
    const agentDetailPage = await openChannels(page);
    const links = await serve(page);
    await page.route(TOKENS, (route) =>
      route.fulfill({ status: 201, json: linkToken("waiting", { url: DEEP_LINK }) }),
    );
    let statusChecks = 0;
    await page.route(`${TOKENS}/${TOKEN_ID}`, (route) => {
      statusChecks += 1;
      if (statusChecks >= 2) links.setLinks([linkedAccount]);
      return route.fulfill({ json: linkToken(statusChecks >= 2 ? "linked" : "waiting") });
    });
    await goToChannels(page, agentDetailPage);

    await page.getByRole("button", { name: "Connect Telegram" }).click();

    const open = page.getByRole("link", { name: "Open in Telegram" });
    await expect(open).toHaveAttribute("href", DEEP_LINK);
    await expect(open).toHaveAttribute("target", "_blank");
    await expect(page.getByText("Waiting for you to press Start in Telegram…")).toBeVisible();
    await expect(page.getByText("Linked as @jane_doe")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("telegram-linked-account")).toContainText("@jane_doe");
  });

  test("copies the link for people opening Telegram elsewhere", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const agentDetailPage = await openChannels(page);
    await serve(page);
    await page.route(TOKENS, (route) =>
      route.fulfill({ status: 201, json: linkToken("waiting", { url: DEEP_LINK }) }),
    );
    await page.route(`${TOKENS}/${TOKEN_ID}`, (route) => route.fulfill({ json: linkToken("waiting") }));
    await goToChannels(page, agentDetailPage);

    await page.getByRole("button", { name: "Connect Telegram" }).click();
    await page.getByRole("button", { name: "Copy link" }).click();

    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(DEEP_LINK);
  });

  test("offers a new link once the old one expires", async ({ page }) => {
    const agentDetailPage = await openChannels(page);
    await serve(page);
    // Every link the API issues has its own id, so the fresh one starts out waiting.
    const FRESH_TOKEN_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee2";
    let issued = 0;
    await page.route(TOKENS, (route) => {
      issued += 1;
      const id = issued === 1 ? TOKEN_ID : FRESH_TOKEN_ID;
      return route.fulfill({ status: 201, json: linkToken("waiting", { id, url: `${DEEP_LINK}${issued}` }) });
    });
    await page.route(`${TOKENS}/${TOKEN_ID}`, (route) => route.fulfill({ json: linkToken("expired") }));
    await page.route(`${TOKENS}/${FRESH_TOKEN_ID}`, (route) =>
      route.fulfill({ json: linkToken("waiting", { id: FRESH_TOKEN_ID }) }),
    );
    await goToChannels(page, agentDetailPage);

    await page.getByRole("button", { name: "Connect Telegram" }).click();
    await expect(page.getByText("That link expired.")).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Get a new link" }).click();

    await expect(page.getByRole("link", { name: "Open in Telegram" })).toHaveAttribute("href", `${DEEP_LINK}2`);
  });

  test("unlinks an account after confirmation", async ({ page }) => {
    const agentDetailPage = await openChannels(page);
    const links = await serve(page, { links: [linkedAccount] });
    let unlinked = false;
    await page.route(`${LINKS}/${LINK_ID}`, (route) => {
      unlinked = true;
      links.setLinks([]);
      return route.fulfill({ status: 204, body: "" });
    });
    await goToChannels(page, agentDetailPage);

    await expect(page.getByTestId("telegram-linked-account")).toContainText("@jane_doe");
    await page.getByRole("button", { name: "Unlink @jane_doe" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Unlink", exact: true }).click();

    await expect(page.getByTestId("telegram-linked-account")).toHaveCount(0);
    expect(unlinked).toBe(true);
  });

  test("asks for the connection to be turned on before linking", async ({ page }) => {
    const agentDetailPage = await openChannels(page);
    await serve(page, { enabled: false });
    await goToChannels(page, agentDetailPage);

    await expect(page.getByText("Turn this connection on to link Telegram accounts.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Connect Telegram" })).toHaveCount(0);
  });

  test("shows linked accounts to viewers without letting them change anything", async ({ page }) => {
    const agentDetailPage = await openChannels(page, ["agent.read", "activity.read"]);
    await serve(page, { links: [linkedAccount] });
    await goToChannels(page, agentDetailPage);

    await expect(page.getByTestId("telegram-linked-account")).toContainText("@jane_doe");
    await expect(page.getByRole("button", { name: "Connect Telegram" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Unlink @jane_doe" })).toHaveCount(0);
  });
});
