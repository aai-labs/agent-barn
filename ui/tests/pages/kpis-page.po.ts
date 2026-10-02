import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for the organization KPIs page. Assertions live in the spec. */
export class KpisPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/kpis`);
  }

  async gotoHome() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}`);
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "KPIs", exact: true });
  }

  inlineNavLinks(): Locator {
    return this.page.locator("header nav").getByRole("link");
  }

  inlineNavLink(name: string): Locator {
    return this.page.locator("header nav").getByRole("link", { name, exact: true });
  }

  async openNavigationDrawer() {
    await this.page.getByRole("button", { name: "Open navigation" }).click();
  }

  drawer(): Locator {
    return this.page.getByRole("dialog");
  }

  drawerLinks(): Locator {
    return this.drawer().getByRole("link");
  }

  drawerLink(name: string): Locator {
    return this.drawer().getByRole("link", { name, exact: true });
  }
}
