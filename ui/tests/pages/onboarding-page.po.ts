import { Locator, Page } from "@playwright/test";

export class OnboardingPage {
  constructor(private page: Page) {}

  async gotoSignup(error?: string) {
    await this.page.goto(error ? `/signup?error=${error}` : "/signup");
  }

  async goto() {
    await this.page.goto("/onboarding");
  }

  async chooseQuickStart() {
    await this.continueAction().click();
  }

  async chooseOwnAgent() {
    await this.page.getByRole("radio", { name: /Build my own agent/ }).click();
    await this.continueAction().click();
  }

  agentName() { return this.page.getByLabel("Agent name"); }
  template() { return this.page.getByRole("radio", { name: /General Purpose/ }); }
  hireAction() { return this.page.getByRole("button", { name: "Hire agent", exact: true }); }
  skipAction() { return this.page.getByRole("button", { name: "Skip, I'll chat on the web" }); }
  laterAction() { return this.page.getByRole("button", { name: "I'll do this later" }); }
  templateGroup() { return this.page.getByRole("radiogroup", { name: "Template", exact: true }); }

  step(label: string): Locator {
    return this.page.getByText(label, { exact: true });
  }

  stepCounter(): Locator {
    return this.page.getByText(/^Step \d of 4$/);
  }

  heading(name: string | RegExp): Locator {
    return this.page.getByRole("heading", { name });
  }

  continueWithGoogle(): Locator {
    return this.page.getByRole("link", { name: "Continue with Google" });
  }

  // Not the bare role: Next's route announcer is an (empty) alert too.
  alert(): Locator {
    return this.page.getByRole("alert").filter({ hasText: /\S/ });
  }

  openInTelegram(): Locator {
    return this.page.getByRole("link", { name: /^Open in Telegram/ });
  }

  copyLink(): Locator {
    return this.page.getByRole("button", { name: "Copy link" });
  }

  continueAction(): Locator {
    return this.page.getByRole("button", { name: "Continue" });
  }

  retryAction(): Locator {
    return this.page.getByRole("button", { name: "Try again" });
  }

  openTelegram(): Locator {
    return this.page.getByRole("link", { name: "Open Telegram" });
  }

  goToDashboard(): Locator {
    return this.page.getByRole("button", { name: "Go to dashboard" });
  }

  summaryRow(label: string): Locator {
    return this.page.getByTestId(`onboarding-summary-${label.toLowerCase()}`);
  }
}
