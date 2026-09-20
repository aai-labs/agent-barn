import { Locator, Page } from "@playwright/test";

export class AgentConfigurationPage {
  constructor(private page: Page) {}

  async goto(agentId: string, orgId: string) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}/configuration`);
  }

  profileHeading(): Locator {
    return this.page.getByRole("heading", { name: "Profile", exact: true });
  }

  sectionButton(name: string): Locator {
    return this.page.getByRole("button", { name, exact: true });
  }

  startDraftButton(): Locator {
    return this.page.getByRole("button", { name: /create override|start override draft/i });
  }

  draftHeading(): Locator {
    return this.page.getByRole("heading", { name: "Override Draft" });
  }

  artifact(name: string): Locator {
    return this.page.getByRole("textbox", { name: `${name} content` });
  }

  saveDraftButton(): Locator {
    return this.page.getByRole("button", { name: /save draft/i });
  }

  publishButton(): Locator {
    return this.page.getByRole("button", { name: /^publish$/i });
  }

  publishConfirmButton(): Locator {
    return this.page.getByRole("button", { name: /publish override/i });
  }

  versionSelect(): Locator {
    return this.page.getByRole("combobox", { name: "Template version" });
  }

  applyButton(): Locator {
    return this.page.getByRole("button", { name: /^Apply(?: & Restart)?$/i });
  }

  applyConfirmationButton(): Locator {
    return this.page
      .getByRole("dialog")
      .getByRole("button", { name: /^Apply(?: & Restart)?$/i });
  }

  captureRestorePointButton(): Locator {
    return this.page.getByRole("button", { name: /capture restore point/i });
  }

  captureAction(): Locator {
    return this.page.getByTestId("capture-action");
  }

  restorePointRows(): Locator {
    return this.page.getByTestId("restore-point-row");
  }

  restorePointRow(label: string): Locator {
    return this.restorePointRows().filter({ hasText: label });
  }

  restoreButton(): Locator {
    return this.page.getByRole("button", { name: /^Restore$/ });
  }

  restoreConfirmNameInput(): Locator {
    return this.page.getByRole("dialog").getByLabel(/type .* to confirm/i);
  }

  restoreConfirmButton(): Locator {
    return this.page.getByRole("dialog").getByRole("button", { name: /restore agent/i });
  }

  reapplyConfigurationCheckbox(): Locator {
    return this.page.getByRole("checkbox", {
      name: /also re-apply the recorded configuration/i,
    });
  }
}
