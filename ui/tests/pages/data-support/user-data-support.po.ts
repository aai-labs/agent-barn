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
    pages,
    failAfterRequests = 0,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
    pages?: unknown[][];
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
      const page = Number(new URL(route.request().url()).searchParams.get("page") ?? "1");
      const pageItems = pages?.[page - 1] ?? [];

      await route.fulfill({
        status: shouldFail ? status : 200,
        contentType: "application/json",
        body: JSON.stringify(
          shouldFail
            ? {
                detail,
                page,
                page_size: 20,
                total: 0,
                items: [],
            }
            : (body ?? {
                page,
                page_size: 20,
                total: pages?.flat().length ?? 1,
                items: pages ? pageItems : [
                  {
                    id: "11111111-1111-4111-8111-111111111111",
                    created_at: "2024-01-01T00:00:00Z",
                    updated_at: "2024-01-01T00:00:00Z",
                    full_name: "Ada Lovelace",
                    email: "ada@example.com",
                    is_platform_admin: false,
                    email_verified_at: null,
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
            user: {
              id: "22222222-2222-4222-8222-222222222222",
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
              full_name: "New User",
              email: "new@example.com",
              is_platform_admin: false,
              email_verified_at: null,
              organization_users: [],
            },
            organization: {
              id: "33333333-3333-4333-8333-333333333333",
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:00Z",
              name: "New User Studio",
              description: null,
              owner_email: "new@example.com",
              owner_name: "New User",
            },
            invite_link: "http://localhost:3000/set-password?token=new-user-token",
          },
        ),
      });
    });
  }

  async interceptResendUserInviteRequest({
    success = true,
    status = 409,
    detail = "An active user does not need an invitation",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(
      "**/api/v1/platform/users/*/resend-invite",
      async (route) => {
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
            invite_link:
              "http://localhost:3000/set-password?token=resent-user-token",
          }),
        });
      },
    );
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

  async interceptPlatformPrivilegeRequest({
    success = true,
    status = 409,
    detail = "Platform Privilege is already in the requested state",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(
      "**/api/v1/platform/users/*/platform-privilege",
      async (route) => {
        if (route.request().method() !== "PATCH") {
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
        const request = route.request().postDataJSON() as {
          is_platform_admin?: boolean;
          isPlatformAdmin?: boolean;
        };
        const isPlatformAdmin =
          request.is_platform_admin ?? request.isPlatformAdmin ?? false;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "11111111-1111-4111-8111-111111111111",
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            full_name: "Ada Lovelace",
            email: "ada@example.com",
            is_platform_admin: isPlatformAdmin,
            email_verified_at: "2024-01-01T00:00:00Z",
          }),
        });
      },
    );
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

  async interceptGetPlatformUser({
    userId = "11111111-1111-4111-8111-111111111111",
    user,
    status = 200,
    detail = "User not found",
  }: {
    userId?: string;
    user?: unknown;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(`**/api/v1/platform/users/${userId}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail }
            : (user ?? {
                id: userId,
                created_at: "2024-01-01T00:00:00Z",
                updated_at: "2024-01-01T00:00:00Z",
                full_name: "Ada Lovelace",
                email: "ada@example.com",
                is_platform_admin: false,
                email_verified_at: "2024-01-01T00:00:00Z",
                organization_users: [],
              }),
        ),
      });
    });
  }
}
