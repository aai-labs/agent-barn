import { Page } from "@playwright/test";

import UserContext from "../../fixtures/user-context.json";

export class UserDataSupport {
  constructor(private page: Page) {}

  async interceptGetUserContextRequest({
    userContext,
    unauthorized = false,
    status = 200,
    detail = "Unable to load user context",
  }: {
    userContext?: unknown;
    unauthorized?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/me", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }

      if (unauthorized) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unauthorized" }),
        });
        return;
      }

      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400 ? { detail } : (userContext ?? UserContext),
        ),
      });
    });
  }

  async interceptGetUsersRequest({
    status = 200,
    detail = "Unable to load users",
    body,
    failAfterRequests = 0,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
    failAfterRequests?: number;
  } = {}) {
    let requestCount = 0;

    await this.page.route("**/api/v1/platform/users**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }

      requestCount += 1;
      const shouldFail = status >= 400 && requestCount > failAfterRequests;

      await route.fulfill({
        status: shouldFail ? status : 200,
        contentType: "application/json",
        body: JSON.stringify(
          shouldFail
            ? {
                detail,
                page: 1,
                page_size: 20,
                total: 0,
                items: [],
              }
            : (body ?? {
                page: 1,
                page_size: 20,
                total: 1,
                items: [
                  {
                    id: "11111111-1111-4111-8111-111111111111",
                    created_at: "2024-01-01T00:00:00Z",
                    updated_at: "2024-01-01T00:00:00Z",
                    full_name: "Ada Lovelace",
                    email: "ada@example.com",
                    is_platform_admin: false,
                    email_verified_at: "2024-01-01T00:00:00Z",
                  },
                ],
              }),
        ),
      });
    });
  }

  async interceptCreateUserRequest({
    success = true,
    status = 201,
    detail = "Email is already taken",
    user,
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
    user?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/platform/users", async (route) => {
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

      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          user ?? {
            id: "22222222-2222-4222-8222-222222222222",
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            full_name: "New User",
            email: "new@example.com",
            is_platform_admin: false,
            email_verified_at: null,
          },
        ),
      });
    });
  }

  async interceptDeleteUserRequest({
    success = true,
    status = 400,
    detail = "Cannot delete your own account",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/platform/users/**", async (route) => {
      if (route.request().method() !== "DELETE") {
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

      await route.fulfill({ status: 204 });
    });
  }

  async interceptResetUserPasswordRequest({
    success = true,
    status = 400,
    detail = "Password must be at least 8 characters",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/platform/users/*/reset-password", async (route) => {
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

      await route.fulfill({ status: 204 });
    });
  }

  async interceptChangePasswordRequest({
    success = true,
    status = 400,
    detail = "Old password is incorrect",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/me/change-password", async (route) => {
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

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "new-access-token",
          refresh_token: "new-refresh-token",
          token_type: "bearer",
        }),
      });
    });
  }

  async interceptGetOrganizationsRequest({
    status = 200,
    detail = "Unable to load organizations",
    body,
    failAfterRequests = 0,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
    failAfterRequests?: number;
  } = {}) {
    let requestCount = 0;

    await this.page.route("**/api/v1/platform/organizations**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }

      requestCount += 1;
      const shouldFail = status >= 400 && requestCount > failAfterRequests;

      await route.fulfill({
        status: shouldFail ? status : 200,
        contentType: "application/json",
        body: JSON.stringify(
          shouldFail
            ? {
                detail,
                page: 1,
                page_size: 20,
                total: 0,
                items: [],
              }
            : (body ?? {
                page: 1,
                page_size: 20,
                total: 1,
                items: [
                  {
                    id: "22222222-2222-4222-8222-222222222222",
                    created_at: "2024-01-01T00:00:00Z",
                    updated_at: "2024-01-01T00:00:00Z",
                    name: "AAI Labs",
                    description: "Starter organization",
                    is_default: false,
                    owner_email: "owner@example.com",
                    owner_name: "Grace Hopper",
                  },
                ],
              }),
        ),
      });
    });
  }
}
