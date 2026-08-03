import { Page } from "@playwright/test";

export const MOCK_PLATFORM_SKILL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const MOCK_CUSTOM_SKILL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const MOCK_JIRA_SKILL_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const MOCK_GMAIL_SKILL_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
export const MOCK_BITBUCKET_SKILL_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

export const mockPlatformSkill = {
  id: MOCK_PLATFORM_SKILL_ID,
  organizationId: null,
  name: "github",
  source: "aai_cli",
  requiredProviders: ["github"],
  toolsPointer: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockCustomSkill = {
  id: MOCK_CUSTOM_SKILL_ID,
  organizationId: "22222222-2222-4222-8222-222222222222",
  name: "my-tool",
  source: "custom",
  requiredProviders: [],
  toolsPointer: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockJiraSkill = {
  id: MOCK_JIRA_SKILL_ID,
  organizationId: null,
  name: "jira",
  source: "aai_cli",
  requiredProviders: ["jira"],
  toolsPointer: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockGmailSkill = {
  id: MOCK_GMAIL_SKILL_ID,
  organizationId: null,
  name: "gmail",
  source: "aai_cli",
  requiredProviders: ["gmail"],
  toolsPointer: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockBitbucketSkill = {
  id: MOCK_BITBUCKET_SKILL_ID,
  organizationId: null,
  name: "bitbucket",
  source: "aai_cli",
  requiredProviders: ["bitbucket"],
  toolsPointer: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export class SkillDataSupport {
  constructor(private page: Page) {}

  async interceptGetSkillsRequest({
    status = 200,
    detail = "Unable to load skills",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/skills*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      if (!/\/api\/v1\/organizations\/[^/]+\/skills$/.test(url.pathname)) {
        await route.fallback();
        return;
      }

      const search = url.searchParams.get("search")?.toLowerCase();
      const source = url.searchParams.get("source");
      let items = [mockPlatformSkill, mockCustomSkill, mockJiraSkill, mockGmailSkill];
      if (search) {
        items = items.filter((s) => s.name.toLowerCase().includes(search));
      }
      if (source) {
        items = items.filter((s) => s.source === source);
      }

      let responseBody: unknown;
      if (status >= 400) {
        responseBody = { detail };
      } else if (body !== undefined) {
        // Allow callers to pass a flat array (auto-wrapped) or a full paginated object.
        responseBody = Array.isArray(body)
          ? { page: 1, page_size: 15, total: (body as unknown[]).length, items: body }
          : body;
      } else {
        responseBody = { page: 1, page_size: 15, total: items.length, items };
      }

      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(responseBody),
      });
    });
  }

  async interceptDeleteSkillRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 204,
    detail = "Unable to delete skill",
  }: {
    skillId?: string;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status >= 400 ? JSON.stringify({ detail }) : "",
      });
    });
  }
}
