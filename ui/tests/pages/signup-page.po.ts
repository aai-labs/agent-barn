import { Locator, Page } from "@playwright/test";

export class SignupPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/signup");
    await this.page.waitForLoadState("networkidle");
  }

  async signup(fullName: string, email: string, password: string) {
    await this.fullNameField().fill(fullName);
    await this.emailField().fill(email);
    await this.passwordField().fill(password);
    await this.confirmPasswordField().fill(password);
    await this.submitAction().click();
  }

  title(): Locator {
    return this.page.getByText("Create your account");
  }

  fullNameField(): Locator {
    return this.page.locator('input[name="fullName"]');
  }

  emailField(): Locator {
    return this.page.locator('input[type="email"]');
  }

  passwordField(): Locator {
    return this.page.locator('input[name="password"]');
  }

  confirmPasswordField(): Locator {
    return this.page.locator('input[name="confirmPassword"]');
  }

  submitAction(): Locator {
    return this.page.getByRole("button", { name: /create account/i });
  }
}
