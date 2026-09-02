import { Locator, Page } from "@playwright/test";

export class PlatformStatsPage {
  public page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto() {
    await this.page.goto("/dashboard/platform");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Platform" });
  }

  overviewHeading(): Locator {
    return this.page.getByRole("heading", { name: "Overview" });
  }

  activityHeading(): Locator {
    return this.page.getByRole("heading", { name: "Activity" });
  }

  periodSelect(): Locator {
    return this.page.getByRole("combobox", { name: "Reporting period" });
  }

  messagingAppSelect(): Locator {
    return this.page.getByRole("combobox", { name: "Filter by messaging app" });
  }

  openOptions(): Locator {
    return this.page.getByRole("listbox").getByRole("option");
  }
}
