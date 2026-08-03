import { Page } from "@playwright/test";

export const ORG_A_ID = "22222222-2222-4222-8222-222222222222";
export const ORG_B_ID = "33333333-3333-4333-8333-333333333333";
export const OWNER_ID = "44444444-4444-4444-8444-444444444444";
export const MEMBER_ID = "55555555-5555-4555-8555-555555555555";

function org(overrides: Record<string, unknown> = {}) {
  return {
    id: ORG_A_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    is_default: false,
    owner_email: "owner@example.com",
    owner_name: "Grace Hopper",
    allowed_models: ["*"],
    ...overrides,
  };
}

export const DEFAULT_MEMBERS = [
  {
    user_id: OWNER_ID,
    email: "owner@example.com",
    full_name: "Grace Hopper",
    role: "OWNER",
    is_pending: false,
  },
  {
    user_id: MEMBER_ID,
    email: "ada@example.com",
    full_name: "Ada Lovelace",
    role: "MEMBER",
    is_pending: false,
  },
];

/**
 * Route mocks for the organization + membership APIs. Handlers guard on HTTP method and
 * fall back when it doesn't match, so registration order (generic first, specific last)
 * lets Playwright's last-wins routing resolve overlapping globs correctly.
 */
export class OrganizationDataSupport {
  constructor(private page: Page) {}

  async interceptListOrganizations({
    items,
    status = 200,
    detail = "Unable to load organizations",
  }: {
    items?: unknown[];
    status?: number;
    detail?: string;
  } = {}) {
    const list = items ?? [org()];
    await this.page.route("**/api/v1/platform/organizations?*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status >= 400
            ? { detail, page: 1, page_size: 200, total: 0, items: [] }
            : { page: 1, page_size: 200, total: list.length, items: list },
        ),
      });
    });
  }

  async interceptCreateOrganization({
    success = true,
    status = 201,
    detail = "Only a platform_admin can create organizations",
    result,
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
    result?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/platform/organizations", async (route) => {
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
          result ?? {
            organization: org({
              id: ORG_B_ID,
              name: "New Org",
              owner_email: "founder@acme.com",
              owner_name: null,
            }),
            invite_link:
              "http://127.0.0.1:3003/set-password?token=create-token-123",
          },
        ),
      });
    });
  }

  async interceptGetOrganization({
    organization,
    status = 200,
    detail = "Organization not found",
  }: {
    organization?: unknown;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (organization ?? org())),
      });
    });
  }

  async interceptDeleteOrganization({
    success = true,
    status = 409,
    detail = "The default organization cannot be deleted",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*", async (route) => {
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

  async interceptGetMembers({
    members,
    status = 200,
    detail = "Unable to load members",
  }: {
    members?: unknown[];
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/members*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const source = members ?? DEFAULT_MEMBERS;
      const params = new URL(route.request().url()).searchParams;
      const search = params.get("search")?.toLowerCase();
      const limit = params.get("limit");
      let items =
        search && !members
          ? (source as typeof DEFAULT_MEMBERS).filter(
              (m) =>
                m.full_name?.toLowerCase().includes(search) ||
                m.email.toLowerCase().includes(search),
            )
          : source;
      if (limit) items = items.slice(0, Number(limit));
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : items),
      });
    });
  }

  async interceptAddMember({
    success = true,
    status = 201,
    detail = "User is already part of organization",
    result,
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
    result?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/members", async (route) => {
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
          result ?? {
            member: {
              user_id: "66666666-6666-4666-8666-666666666666",
              email: "teammate@example.com",
              full_name: null,
              role: "MEMBER",
              is_pending: true,
            },
            invite_link:
              "http://127.0.0.1:3003/set-password?token=member-token-456",
          },
        ),
      });
    });
  }

  async interceptChangeMemberRole({ success = true } = {}) {
    await this.page.route(
      "**/api/v1/organizations/*/members/*",
      async (route) => {
        if (route.request().method() !== "PATCH") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: success ? 200 : 403,
          contentType: "application/json",
          body: JSON.stringify(
            success
              ? {
                  user_id: MEMBER_ID,
                  email: "ada@example.com",
                  full_name: "Ada Lovelace",
                  role: "ADMIN",
                  is_pending: false,
                }
              : { detail: "You don't have permission" },
          ),
        });
      },
    );
  }

  async interceptRemoveMember({ success = true } = {}) {
    await this.page.route(
      "**/api/v1/organizations/*/members/*",
      async (route) => {
        if (route.request().method() !== "DELETE") {
          await route.fallback();
          return;
        }
        if (!success) {
          await route.fulfill({
            status: 403,
            contentType: "application/json",
            body: JSON.stringify({ detail: "You don't have permission" }),
          });
          return;
        }
        await route.fulfill({ status: 204 });
      },
    );
  }

  async interceptSetPassword({
    success = true,
    status = 400,
    detail = "This invite link is invalid or has expired.",
  }: {
    success?: boolean;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/auth/set-password", async (route) => {
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
}
