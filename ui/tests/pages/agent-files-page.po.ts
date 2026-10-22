import type { Page } from "@playwright/test";
import { TEST_ORG_ID } from "../constants";

export class AgentFilesPage {
  constructor(private page: Page) {}
  goto(agentId: string) { return this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}?tab=files`); }
  get files() { return this.page.getByRole("region", {name: "Agent files", exact: true}); }
  download(filename: string) { return this.page.getByRole("button", {name: `Download ${filename}`}).click(); }
}
