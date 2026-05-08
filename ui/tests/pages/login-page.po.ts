import { Locator, Page } from "@playwright/test";

export class LoginPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/login");
    await this.page.waitForLoadState("networkidle");
  }

  async login(email: string, password: string) {
    await this.emailField().fill(email);
    await this.emailField().blur();
    await this.passwordField().fill(password);
    await this.submitAction().click();
  }

  async loginWithEnter(email: string, password: string) {
    await this.emailField().fill(email);
    await this.passwordField().fill(password);
    await this.passwordField().press("Enter");
  }

  title(): Locator {
    return this.page.getByText("Welcome back");
  }

  emailField(): Locator {
    return this.page.locator('input[type="email"]');
  }

  passwordField(): Locator {
    return this.page.locator('input[name="password"]');
  }

  submitAction(): Locator {
    return this.page.getByRole("button", { name: /login/i });
  }
}
