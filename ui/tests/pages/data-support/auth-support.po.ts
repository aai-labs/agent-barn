import { Page } from "@playwright/test";

import { BaseInterceptor } from "./base-intercepter.po";

export class AuthSupport extends BaseInterceptor {
  constructor(page: Page) {
    super(page);
  }

  async interceptLoginRequest({
    success = true,
    accessToken = "fake-jwt-token",
    refreshToken = "fake-refresh-token",
    tokenType = "bearer",
    detail = "Invalid email or password, please try again.",
  }: {
    success?: boolean;
    accessToken?: string;
    refreshToken?: string;
    tokenType?: string;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/login", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }

      if (success) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            access_token: accessToken,
            refresh_token: refreshToken,
            token_type: tokenType,
          }),
        });
        return;
      }

      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail }),
      });
    });
  }

  async interceptSignupRequest({
    success = true,
    accessToken = "fake-jwt-token",
    refreshToken = "fake-refresh-token",
    tokenType = "bearer",
    status = 201,
    detail = "An account already exists for this email",
  }: {
    success?: boolean;
    accessToken?: string;
    refreshToken?: string;
    tokenType?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/signup", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }

      if (success) {
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({
            access_token: accessToken,
            refresh_token: refreshToken,
            token_type: tokenType,
          }),
        });
        return;
      }

      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify({ detail }),
      });
    });
  }

  async interceptForgotPasswordRequest() {
    await this.page.route("**/api/v1/auth/forgot-password", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ message: "Password reset email sent" }),
      });
    });
  }

  async interceptResetPasswordRequest({
    success = true,
    status = 400,
    detail = "This reset link is invalid or has expired.",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/reset-password", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      if (!success) {
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail }),
        });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
  }

  async interceptLogoutRequest() {
    await this.page.route("**/api/v1/auth/logout", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ message: "Successfully logged out" }),
      });
    });
  }

  async interceptRefreshRequest({
    accessToken = "refreshed-jwt-token",
    refreshToken = "refreshed-refresh-token",
    tokenType = "bearer",
    expiresAt,
  }: {
    accessToken?: string;
    refreshToken?: string;
    tokenType?: string;
    expiresAt?: number;
  } = {}) {
    await this.page.route("**/api/v1/auth/refresh", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: accessToken,
          refresh_token: refreshToken,
          token_type: tokenType,
          ...(expiresAt ? { expires_at: expiresAt } : {}),
        }),
      });
    });
  }
}
