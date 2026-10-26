import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

export class AgentFileSyncPage {
  constructor(private page: Page) {}

  async goto(agentId: string) {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}?tab=file-sync`);
  }

  card(): Locator {
    return this.page.getByRole("region", { name: "File sync", exact: true });
  }

  openFolderLink(): Locator {
    return this.card().getByRole("link", { name: /^Open in / });
  }

  organizationSettingsLink(): Locator {
    return this.card().getByRole("link", { name: "Organization settings" });
  }

  syncSwitch(): Locator {
    return this.card().getByRole("checkbox", { name: "Sync this agent's files" });
  }

  activityList(): Locator {
    return this.page.getByRole("region", { name: "File sync activity" });
  }

  activityEntries(): Locator {
    return this.activityList().getByRole("listitem");
  }

  loadMoreButton(): Locator {
    return this.activityList().getByRole("button", { name: "Load more" });
  }

  activityRetryButton(): Locator {
    return this.activityList().getByRole("button", { name: "Retry" });
  }

  retryButton(): Locator {
    return this.page.getByRole("button", { name: "Retry" });
  }

  /** A section link in the navigation panel beside the page. */
  sectionLink(name: string): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name, exact: true });
  }
}
