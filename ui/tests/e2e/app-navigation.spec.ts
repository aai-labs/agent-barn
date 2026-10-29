import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import UserContext from "../fixtures/user-context.json";
import { AppNavigation } from "../pages/app-navigation.po";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const OTHER_AGENT_ID = "44444444-4444-4444-8444-444444444444";
const OTHER_ORG_ID = "55555555-5555-4555-8555-555555555555";

/**
 * The dashboard navigation: a rail of destinations, a path bar that switches
 * Organization (or enters Platform View) and Agent, and a panel of the current page's
 * sections. On a phone the rail becomes a bottom bar and the panel a sheet.
 */
test.describe("App navigation", () => {
  let navigation: AppNavigation;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    navigation = new AppNavigation(page);
    const data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.users.interceptGetUsersRequest();
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentRequest();
    await data.agents.interceptGetAgentTemplateRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetConversationChannelsRequest();
    await data.agents.interceptGetModelsRequest();
  });

  const horizontalOverflow = (page: Page) =>
    page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

  test.describe("on a desktop viewport", () => {
    test("moves to another Agent on the same section, without the first Agent's thread", async ({ page }) => {
      await new DataSupport(page).agents.interceptGetAgentsRequest({
        body: {
          page: 1,
          page_size: 50,
          total: 2,
          items: [mockAgent, { ...mockAgent, id: OTHER_AGENT_ID, name: "Sam" }],
        },
      });
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=chat&thread=thread-of-maya`);

      await navigation.agentSwitcher().click();
      await navigation.menuItemMatching(/Sam/).click();

      await expect(page).toHaveURL(new RegExp(`/agents/${OTHER_AGENT_ID}\\?tab=chat$`));
    });

    test("switching Organization from an Agent lands on the other Organization's team", async ({ page }) => {
      const data = new DataSupport(page);
      const [membership] = UserContext.organization_users;
      await data.users.interceptGetUserContextRequest({
        userContext: {
          ...UserContext,
          organization_users: [
            membership,
            {
              ...membership,
              id: "66666666-6666-4666-8666-666666666666",
              organization: { ...membership.organization, id: OTHER_ORG_ID, name: "Globex" },
            },
          ],
        },
      });
      await navigation.gotoAgent(MOCK_AGENT_ID);
      await expect(navigation.agentSwitcher()).toHaveAccessibleName(/Maya/);

      await navigation.contextSwitcher().click();
      await navigation.menuItemMatching(/Globex/).click();

      await expect(page).toHaveURL(new RegExp(`/dashboard/${OTHER_ORG_ID}$`));
    });

    test("keeps the Agent's notices above a full-page Chat", async ({ page }) => {
      await new DataSupport(page).agents.interceptGetAgentRequest({
        body: { ...mockAgent, status: "RUNNING", pending_model: "openrouter/anthropic/claude-opus-5.5" },
      });
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=chat`);

      await expect(page.getByTestId("agent-pending-model-banner")).toBeVisible();
      await expect(navigation.newChat()).toBeVisible();
    });

    test("lists the organization's pages on the rail, with no way into Platform there", async () => {
      await navigation.gotoHome();

      for (const name of ["Team", "Usage", "Costs", "KPIs", "Members", "Settings"]) {
        await expect(navigation.mainLink(name)).toBeVisible();
      }
      await expect(navigation.mainLink("Team")).toHaveAttribute("aria-current", "page");
      await expect(navigation.mainLink("Platform")).toHaveCount(0);
    });

    test("enters Platform View from the path bar, which swaps the rail for Platform's areas", async ({
      page,
    }) => {
      await navigation.gotoHome();

      await navigation.contextSwitcher().click();
      await navigation.chooseMenuItem("Platform admin");

      await expect(page).toHaveURL(/\/dashboard\/platform(\?|$)/);
      await expect(navigation.mainLink("Users")).toBeVisible();
      await expect(navigation.mainLink("Orgs")).toBeVisible();
      await expect(navigation.mainLink("Team")).toHaveCount(0);
      await expect(navigation.contextSwitcher()).toHaveAccessibleName(/Platform admin/);
    });

    test("names the whole way to a section in the path bar, each earlier step a link", async ({ page }) => {
      await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);

      await expect(navigation.breadcrumbCurrent()).toHaveText("Models");
      await expect(navigation.breadcrumb().getByRole("link", { name: "Settings", exact: true })).toHaveAttribute(
        "href",
        `/dashboard/${TEST_ORG_ID}/settings`,
      );
      // The section is the page's heading; the path bar and panel say it is Settings.
      await expect(page.getByRole("heading", { name: "Models", level: 1 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Settings", exact: true })).toHaveCount(0);
    });

    test("keeps Settings sections flat and orders the Agents panel", async ({ page }) => {
      await new DataSupport(page).platformMemory.intercept();
      await navigation.gotoPlatform("/settings?section=agent-memory");

      await expect(navigation.mainLink("Settings")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Agent Memory")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Agent sizes")).toBeVisible();
      await expect(navigation.panelLink("Signup & trials")).toBeVisible();
      await expect(navigation.breadcrumb()).toContainText("Settings/Agent Memory");
      await expect(navigation.panelSections()).toHaveCount(7);
      await expect(navigation.panelSections().nth(0)).toHaveText("Agent Memory");

      await navigation.gotoPlatform("/agents");
      const agentPanel = page.getByRole("navigation", { name: "Agents" });
      await expect(agentPanel.getByRole("link").nth(0)).toHaveText("Resource Usage");
      await expect(agentPanel.getByRole("link").nth(1)).toHaveText("Specs");
      await expect(navigation.mainLink("Agents")).toHaveAttribute("href", "/dashboard/platform/agents");
      await expect(navigation.panelLink("Specs")).toHaveAttribute("aria-current", "page");
    });

    test("keeps Platform View around your Account when you open it from there", async ({ page }) => {
      await navigation.gotoPlatform("/users");

      await navigation.accountMenu().click();
      await navigation.menuItem("Account").click();

      await expect(page).toHaveURL(/\/dashboard\/account$/);
      await expect(navigation.contextSwitcher()).toHaveAccessibleName(/Platform admin/);
      await expect(navigation.mainLink("Users")).toBeVisible();
      await expect(navigation.mainLink("Team")).toHaveCount(0);
    });

    test("moves between an Agent's sections in place, without a server round trip", async ({ page }) => {
      await navigation.gotoAgent(MOCK_AGENT_ID);
      await expect(navigation.panelLink("Chat")).toBeVisible();
      const serverRequests: string[] = [];
      // A navigation's server request, not the prefetches a production build makes for
      // the links on the page.
      page.on("request", (request) => {
        const headers = request.headers();
        if (headers["rsc"] && !headers["next-router-prefetch"]) serverRequests.push(request.url());
      });

      await navigation.panelLink("Tool calls").click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Tool calls");
      await navigation.panelLink("Logs").click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Logs");

      expect(serverRequests).toEqual([]);
    });

    test("goes from Chat's Overview to Conversations without showing Chat's threads again", async ({ page }) => {
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=chat`);
      await navigation.backToOverview().click();
      await expect(navigation.panelLink("Conversations")).toBeVisible();
      // Records any New chat button the panel draws from here on, however briefly.
      await page.evaluate(() => {
        const seen = { newChat: false };
        (window as unknown as { __seen: typeof seen }).__seen = seen;
        new MutationObserver(() => {
          const panel = document.querySelector("aside");
          if (panel && [...panel.querySelectorAll("button")].some((b) => b.textContent?.includes("New chat"))) {
            seen.newChat = true;
          }
        }).observe(document.body, { childList: true, subtree: true });
      });

      await navigation.panelLink("Conversations").click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Conversations");
      await expect(navigation.backToOverview()).toBeVisible();

      expect(await page.evaluate(() => (window as unknown as { __seen: { newChat: boolean } }).__seen.newChat)).toBe(false);
    });

    test("loads Conversations' channels as the pointer arrives, so the panel never empties", async ({ page }) => {
      let channelRequests = 0;
      // Slow enough that, without fetching ahead, the panel would show its loading rows.
      await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/conversations/channels`, async (route) => {
        channelRequests += 1;
        await new Promise((resolve) => setTimeout(resolve, 600));
        await route.fulfill({ json: [] });
      });
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=chat`);
      await navigation.backToOverview().click();
      await page.evaluate(() => {
        const seen = { loading: false };
        (window as unknown as { __seen: typeof seen }).__seen = seen;
        new MutationObserver(() => {
          if (document.querySelector('aside [aria-label="Loading conversations"]')) seen.loading = true;
        }).observe(document.body, { childList: true, subtree: true });
      });

      await navigation.panelLink("Conversations").hover();
      await expect.poll(() => channelRequests).toBe(1);
      await page.waitForTimeout(800);
      await navigation.panelLink("Conversations").click();

      await expect(page.getByRole("complementary")).toContainText("No conversations yet.");
      // The list may refresh in the background on arrival; it shows the fetched one meanwhile.
      expect(await page.evaluate(() => (window as unknown as { __seen: { loading: boolean } }).__seen.loading)).toBe(false);
    });

    test("gives the Agent's logs the page's whole height, as Chat has", async ({ page }) => {
      await new DataSupport(page).agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
      await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/logs`, (route) =>
        route.fulfill({ json: { lines: ["agent started"], source: "snapshot" } }),
      );
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=logs`);

      await page.setViewportSize({ width: 1440, height: 1000 });
      const log = page.getByText("agent started", { exact: true });
      await expect(log).toBeVisible();
      // The scrolling log box keeps the page's width and margins, and grows down to the
      // page's bottom margin instead of stopping at 32rem.
      const box = await log.evaluate((line) => line.parentElement!.getBoundingClientRect());
      expect(box.height).toBeGreaterThan(32 * 16 + 100);
      expect(box.bottom).toBeGreaterThan(1000 - 100);
      expect(box.left).toBeGreaterThan(340);
    });

    test("keeps Members inside the Organization, with no way back to Platform View", async ({ page }) => {
      await page.goto(`/dashboard/${TEST_ORG_ID}/members`);

      await expect(navigation.mainLink("Members")).toHaveAttribute("aria-current", "page");
      await expect(page.locator('main a[href^="/dashboard/platform"]')).toHaveCount(0);
    });

    test("shows each Platform area panel and keeps Resource Usage out of Spend", async () => {
      await navigation.gotoPlatform("/users");
      await expect(navigation.breadcrumbCurrent()).toHaveText("Users");
      await expect(navigation.panels()).toHaveCount(0);

      await navigation.gotoPlatform("/costs");
      await expect(navigation.panelLink("Costs")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Billing")).toBeVisible();
      await expect(navigation.panelLink("Resource Usage")).toHaveCount(0);

      await navigation.gotoPlatform();
      await expect(navigation.panelSections()).toHaveText(["Overview", "Health", "Resource Usage", "Events"]);

      await navigation.gotoPlatform("/agents/resource-usage");
      await expect(navigation.mainLink("Agents")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Resource Usage")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Specs")).toBeVisible();
      await expect(navigation.breadcrumb()).toContainText("Agents/Resource Usage");
    });

    test("opens an Agent on its Overview, listed first among its sections", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await expect(navigation.agentSwitcher()).toHaveAccessibleName(/Maya/);
      await expect(navigation.breadcrumbCurrent()).toHaveText("Overview");
      await expect(navigation.panelSections().first()).toHaveText("Overview");
      await expect(navigation.panelLink("Overview")).toHaveAttribute("aria-current", "page");
    });

    test("gives Chat the panel for its threads, with a way up to the Overview and back", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.panelLink("Chat").click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Chat");
      await expect(navigation.newChat()).toBeVisible();

      await navigation.backToOverview().click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Overview");
      await expect(navigation.panelLink("Overview")).toHaveAttribute("aria-current", "page");
      await expect(navigation.newChat()).toHaveCount(0);

      await navigation.panelLink("Chat").click();
      await expect(navigation.newChat()).toBeVisible();
    });

    test("lists the team's Agents in the Agent switcher", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.agentSwitcher().click();
      await expect(navigation.menuItemMatching(/Maya/)).toBeVisible();
      await expect(navigation.menuItem("All agents")).toBeVisible();
    });

    test("keeps the account menu to the account and logging out", async () => {
      await navigation.gotoHome();

      await navigation.accountMenu().click();
      await expect(navigation.menuItem("Account")).toBeVisible();
      await expect(navigation.menuItem("Log out")).toBeVisible();
      await expect(navigation.menuItem("Platform admin")).toHaveCount(0);
    });
  });

  test.describe("on a phone viewport", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("does not scroll the organization or the Platform view sideways", async ({ page }) => {
      await navigation.gotoHome();
      await expect(navigation.mainLink("Team")).toBeVisible();
      expect(await horizontalOverflow(page)).toBe(0);

      await navigation.gotoPlatform("/users");
      await expect(navigation.mainLink("Users")).toBeVisible();
      expect(await horizontalOverflow(page)).toBe(0);
    });

    test("keeps the rail's first pages in the bottom bar and the rest under More", async () => {
      await navigation.gotoHome();

      await expect(navigation.mainLink("Team")).toBeVisible();
      await expect(navigation.mainLink("KPIs")).toHaveCount(0);

      await navigation.moreButton().click();
      await expect(navigation.sheet().getByRole("link", { name: "KPIs", exact: true })).toBeVisible();
      await expect(navigation.sheet().getByRole("link", { name: "Account", exact: true })).toBeVisible();
    });

    test("offers creating an Organization under More, with only one Organization", async ({ page }) => {
      await navigation.gotoHome();

      await navigation.moreButton().click();
      await navigation.sheet().getByRole("button", { name: "Create organization" }).click();

      await expect(page.getByRole("dialog", { name: "Create organization" })).toBeVisible();
    });

    test("opens the Agent's sections as a sheet from the top bar", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.sectionsSheetTrigger("Overview").click();
      await expect(navigation.sheet().getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    });
  });
});
