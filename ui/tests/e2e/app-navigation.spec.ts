import { expect, test, type Page } from "@playwright/test";

import { AppNavigation } from "../pages/app-navigation.po";
import { MOCK_AGENT_ID } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

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

      await expect(page).toHaveURL(/\/dashboard\/platform$/);
      await expect(navigation.mainLink("Users")).toBeVisible();
      await expect(navigation.mainLink("Orgs")).toBeVisible();
      await expect(navigation.mainLink("Team")).toHaveCount(0);
      await expect(navigation.contextSwitcher()).toHaveAccessibleName(/Platform admin/);
    });

    test("shows a panel only for a Platform area with more than one page", async () => {
      await navigation.gotoPlatform("/users");
      await expect(navigation.breadcrumbCurrent()).toHaveText("Users");
      await expect(navigation.panels()).toHaveCount(0);

      await navigation.gotoPlatform("/costs");
      await expect(navigation.panelLink("Costs")).toHaveAttribute("aria-current", "page");
      await expect(navigation.panelLink("Resources")).toBeVisible();
    });

    test("opens an Agent on its Overview, listed first among its sections", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await expect(navigation.agentSwitcher()).toHaveAccessibleName(/Maya/);
      await expect(navigation.breadcrumbCurrent()).toHaveText("Overview");
      await expect(navigation.panelSections().first()).toHaveText("Overview");
      await expect(navigation.panelLink("Overview")).toHaveAttribute("aria-current", "page");
    });

    test("gives Chat the panel for its threads, with a way back to the sections", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.panelLink("Chat").click();
      await expect(navigation.breadcrumbCurrent()).toHaveText("Chat");
      await expect(navigation.newChat()).toBeVisible();

      await navigation.backToSections().click();
      await expect(navigation.panelLink("Chat")).toHaveAttribute("aria-current", "page");
      await expect(navigation.newChat()).toHaveCount(0);
    });

    test("lists the team's Agents in the Agent switcher", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.agentSwitcher().click();
      await expect(navigation.menuItem("Maya")).toBeVisible();
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

    test("opens the Agent's sections as a sheet from the top bar", async () => {
      await navigation.gotoAgent(MOCK_AGENT_ID);

      await navigation.sectionsSheetTrigger("Overview").click();
      await expect(navigation.sheet().getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    });
  });
});
