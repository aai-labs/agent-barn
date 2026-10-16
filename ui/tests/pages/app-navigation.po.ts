import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** The dashboard's navigation: the rail, the path bar, the section panel and their phone forms. */
export class AppNavigation {
  constructor(private page: Page) {}

  async gotoHome() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}`);
  }

  async gotoAgent(agentId: string) {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}`);
  }

  async gotoPlatform(path = "") {
    await this.page.goto(`/dashboard/platform${path}`);
  }

  /** The rail on desktop; the bottom bar on a phone. Only one of them is shown. */
  mainNavigation(): Locator {
    return this.page.getByRole("navigation", { name: "Main" });
  }

  mainLink(name: string): Locator {
    return this.mainNavigation().getByRole("link", { name, exact: true });
  }

  breadcrumb(): Locator {
    return this.page.getByRole("navigation", { name: "Breadcrumb" });
  }

  breadcrumbCurrent(): Locator {
    return this.breadcrumb().locator('[aria-current="page"]');
  }

  contextSwitcher(): Locator {
    return this.page.getByRole("button", { name: /^Switch organization/ });
  }

  agentSwitcher(): Locator {
    return this.page.getByRole("button", { name: /^Switch agent/ });
  }

  accountMenu(): Locator {
    return this.page.getByRole("button", { name: "Account menu" });
  }

  menuItem(name: string): Locator {
    return this.page.getByRole("menuitem", { name, exact: true });
  }

  async chooseMenuItem(name: string) {
    await this.menuItem(name).click();
  }

  /** The section panel beside the page on desktop, named after what it belongs to. */
  panel(): Locator {
    return this.page.getByRole("complementary").filter({ has: this.page.getByRole("navigation") });
  }

  panels(): Locator {
    return this.page.getByRole("complementary");
  }

  panelSections(): Locator {
    return this.panel().getByRole("navigation").getByRole("link");
  }

  panelLink(name: string): Locator {
    return this.panel().getByRole("link", { name, exact: true });
  }

  backToSections(): Locator {
    return this.page.getByRole("button", { name: "Sections", exact: true });
  }

  newChat(): Locator {
    return this.page.getByRole("button", { name: "New chat", exact: true });
  }

  /** The phone's More button at the end of the bottom bar. */
  moreButton(): Locator {
    return this.page.getByRole("button", { name: "More", exact: true });
  }

  /** The phone's top-bar button that opens the current page's sections. */
  sectionsSheetTrigger(currentSection: string): Locator {
    return this.page.locator("header").getByRole("button", { name: new RegExp(currentSection) });
  }

  sheet(): Locator {
    return this.page.getByRole("dialog");
  }
}
