import { TEST_ORG_ID } from "../constants";
import { Locator, Page } from "@playwright/test";

export class AgentDetailPage {
  constructor(private page: Page) {}

  async goto(agentId = "33333333-3333-4333-8333-333333333333") {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}`);
  }

  agentName(name: string): Locator {
    return this.page.getByRole("heading", { name });
  }

  configureButton(): Locator {
    return this.page.getByRole("button", { name: /configure/i });
  }

  configDrawerHeading(): Locator {
    return this.page.getByRole("heading", { name: /configure agent/i });
  }

  configDrawerCloseButton(): Locator {
    return this.page.locator("aside").getByRole("button").first();
  }

  hireButton(): Locator {
    return this.page.getByRole("button", { name: /hire agent/i });
  }

  toolCallsTab(): Locator {
    return this.page.getByRole("button", { name: /tool calls/i });
  }

  toolCallRow(toolName: string): Locator {
    return this.page.getByRole("row").filter({ hasText: toolName });
  }

  channelsTab(): Locator {
    return this.page.getByRole("button", { name: /^channels$/i });
  }

  groupPolicySelect(): Locator {
    return this.page.locator("aside").getByLabel(/channel access/i);
  }

  dmPolicySelect(): Locator {
    return this.page.locator("aside").getByLabel(/direct messages/i);
  }

  channelSearchInput(): Locator {
    return this.page
      .locator("aside")
      .getByPlaceholder(/search channels|loading channels/i);
  }

  skillsTab(): Locator {
    return this.page.getByRole("button", { name: /^skills$/i });
  }

  skillsSearchInput(): Locator {
    return this.page.getByPlaceholder("Search skills…");
  }

  addSkillButton(): Locator {
    return this.page.getByRole("button", { name: "Add" });
  }

  removeSkillButton(): Locator {
    return this.page.getByRole("button", { name: "Remove" });
  }

  undoSkillButton(): Locator {
    return this.page.getByRole("button", { name: "Undo" });
  }

  cancelSkillButton(): Locator {
    return this.page.getByRole("button", { name: "Cancel" });
  }

  saveSkillsButton(): Locator {
    return this.page.getByRole("button", { name: "Save changes" });
  }

  keysTab(): Locator {
    return this.page.getByRole("button", { name: /^keys$/i });
  }

  appTokenInput(): Locator {
    return this.page.getByPlaceholder(/xapp-/);
  }

  botTokenInput(): Locator {
    return this.page.getByPlaceholder(/xoxb-/);
  }

  saveTokensButton(): Locator {
    return this.page.getByRole("button", { name: "Save tokens" });
  }

  saveIntegrationsButton(): Locator {
    return this.page.getByRole("button", { name: "Save integrations" });
  }

  removeCredentialButton(): Locator {
    return this.page.getByRole("button", { name: "Remove" });
  }

  undoCredentialButton(): Locator {
    return this.page.getByRole("button", { name: "Undo" });
  }

  shareButton(): Locator {
    return this.page.getByRole("button", { name: /^share$/i });
  }

  shareDialog(): Locator {
    return this.page.getByRole("dialog");
  }

  generalAccessSelect(): Locator {
    return this.shareDialog().getByLabel("General access", { exact: true });
  }

  generalAccessRoleSelect(): Locator {
    return this.shareDialog().getByLabel(/general access role/i);
  }

  memberRoleSelect(email: string): Locator {
    return this.shareDialog().getByLabel(`Access role for ${email}`);
  }

  async removeMember(email: string) {
    await this.memberRoleSelect(email).selectOption({ label: "Remove access" });
  }

  shareSearchInput(): Locator {
    return this.shareDialog().getByPlaceholder(/search members/i);
  }

  addCandidateButton(email: string): Locator {
    return this.shareDialog().getByRole("button", { name: `Add ${email}` });
  }

  saveShareButton(): Locator {
    return this.shareDialog().getByRole("button", { name: /^save$/i });
  }

  cancelShareButton(): Locator {
    return this.shareDialog().getByRole("button", { name: /^cancel$/i });
  }

  shareHelpButton(): Locator {
    return this.shareDialog().getByRole("button", {
      name: /what can each agent access role do/i,
    });
  }

  shareHelpDialog(): Locator {
    return this.page.getByRole("dialog", { name: /agent access roles/i });
  }
}
