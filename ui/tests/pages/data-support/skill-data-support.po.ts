import { Page } from "@playwright/test";

import { MOCK_AGENT_ID } from "./agent-data-support.po";

export const MOCK_PLATFORM_SKILL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const MOCK_CUSTOM_SKILL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const MOCK_JIRA_SKILL_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const MOCK_GOOGLE_WORKSPACE_SKILL_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
export const MOCK_BITBUCKET_SKILL_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

export const mockPlatformSkill = {
  id: MOCK_PLATFORM_SKILL_ID,
  organizationId: null,
  scope: "platform",
  name: "github",
  slug: "github",
  description: null,
  rootDir: "aai-cli",
  entryPath: "github_skill.md",
  source: "aai_cli",
  requiredProviders: ["github"],
  toolsPointer: null,
  version: 1,
  hasDraft: false,
  isAssignedToAgent: false,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockCustomSkill = {
  id: MOCK_CUSTOM_SKILL_ID,
  organizationId: "22222222-2222-4222-8222-222222222222",
  scope: "organization",
  name: "my-tool",
  slug: "my-tool",
  description: null,
  rootDir: "my-tool",
  entryPath: "SKILL.md",
  source: "custom",
  requiredProviders: [],
  toolsPointer: null,
  version: 1,
  hasDraft: false,
  isAssignedToAgent: false,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockJiraSkill = {
  id: MOCK_JIRA_SKILL_ID,
  organizationId: null,
  scope: "platform",
  name: "jira",
  slug: "jira",
  description: null,
  rootDir: "aai-cli",
  entryPath: "jira_skill.md",
  source: "aai_cli",
  requiredProviders: ["jira"],
  toolsPointer: null,
  version: 1,
  hasDraft: false,
  isAssignedToAgent: false,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockGoogleWorkspaceSkill = {
  id: MOCK_GOOGLE_WORKSPACE_SKILL_ID,
  organizationId: null,
  scope: "platform",
  name: "google workspace",
  slug: "google-workspace",
  description: null,
  rootDir: "google-workspace",
  entryPath: "SKILL.md",
  source: "aai_cli",
  requiredProviders: ["google_workspace"],
  toolsPointer: null,
  version: 1,
  hasDraft: false,
  isAssignedToAgent: false,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export const mockBitbucketSkill = {
  id: MOCK_BITBUCKET_SKILL_ID,
  organizationId: null,
  scope: "platform",
  name: "bitbucket",
  slug: "bitbucket",
  description: null,
  rootDir: "aai-cli",
  entryPath: "bitbucket_skill.md",
  source: "aai_cli",
  requiredProviders: ["bitbucket"],
  toolsPointer: null,
  version: 1,
  hasDraft: false,
  isAssignedToAgent: false,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

export class SkillDataSupport {
  constructor(private page: Page) {}

  async interceptGetPlatformSkillsRequest({
    status = 200,
    detail = "Unable to load platform skills",
    body,
  }: {
    status?: number;
    detail?: string;
    body?: unknown;
  } = {}) {
    await this.page.route("**/api/v1/platform/skills*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/v1/platform/skills") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : (body ?? [
          mockPlatformSkill,
          mockJiraSkill,
          mockGoogleWorkspaceSkill,
        ])),
      });
    });
  }

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
      let items = [mockPlatformSkill, mockCustomSkill, mockJiraSkill, mockGoogleWorkspaceSkill];
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

  /** The Agent-scoped skills list (Platform + Organization + this Agent's own
   * private Skills) uses a distinct endpoint from the Organization-scoped list. */
  async interceptGetAgentSkillsRequest({
    agentId = MOCK_AGENT_ID,
    status = 200,
    detail = "Unable to load skills",
    body,
    pages,
    total,
  }: {
    agentId?: string;
    status?: number;
    detail?: string;
    body?: unknown;
    pages?: unknown[][];
    total?: number;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/skills*`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      if (!new RegExp(`/api/v1/organizations/[^/]+/agents/${agentId}/skills$`).test(url.pathname)) {
        await route.fallback();
        return;
      }

      const search = url.searchParams.get("search")?.toLowerCase();
      const source = url.searchParams.get("source");
      const page = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "15");
      let items = [mockPlatformSkill, mockCustomSkill, mockJiraSkill, mockGoogleWorkspaceSkill];
      if (search) items = items.filter((skill) => skill.name.toLowerCase().includes(search));
      if (source) items = items.filter((skill) => skill.source === source);

      const responseBody: unknown =
        status >= 400
          ? { detail }
          : pages !== undefined
            ? {
                page,
                page_size: pageSize,
                total: total ?? pages.flat().length,
                items: pages[page - 1] ?? [],
              }
          : body !== undefined
            ? Array.isArray(body)
              ? { page: 1, page_size: 15, total: body.length, items: body }
              : body
            : { page: 1, page_size: 15, total: items.length, items };

      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(responseBody),
      });
    });
  }

  async interceptGetSkillFilesRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 200,
    files = [{ path: "SKILL.md", content: "# My tool" }],
    skill = mockCustomSkill,
    scope = "organization",
    agentId = MOCK_AGENT_ID,
  }: {
    skillId?: string;
    status?: number;
    files?: { path: string; content: string }[];
    skill?: Record<string, unknown>;
    scope?: "organization" | "platform" | "agent";
    agentId?: string;
  } = {}) {
    const path = scope === "platform"
      ? `**/api/v1/platform/skills/${skillId}/files`
      : scope === "agent"
        ? `**/api/v1/organizations/*/agents/${agentId}/skills/${skillId}/files`
        : `**/api/v1/organizations/*/skills/${skillId}/files`;
    await this.page.route(path, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail: "Unable to load skill files" })
            : JSON.stringify({ ...skill, files }),
      });
    });
  }

  async interceptForkSkillRequest({
    skillId = MOCK_PLATFORM_SKILL_ID,
    status = 201,
    detail = "Unable to fork skill",
    skill,
  }: {
    skillId?: string;
    status?: number;
    detail?: string;
    skill?: Record<string, unknown>;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/fork`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail })
            : JSON.stringify(
                skill ?? {
                  ...mockCustomSkill,
                  name: mockPlatformSkill.name,
                  entryPath: mockPlatformSkill.entryPath,
                  files: [{ path: mockPlatformSkill.entryPath, content: "# GitHub" }],
                  hasDraft: true,
                },
              ),
      });
    });
  }

  async interceptGetSkillDraftRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 200,
    files = [{ path: "SKILL.md", content: "# My tool" }],
  }: {
    skillId?: string;
    status?: number;
    files?: { path: string; content: string }[];
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/draft`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      if (status >= 400) {
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: "No draft" }) });
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify({
          skill_id: skillId,
          files,
          description: null,
          required_providers: [],
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      });
    });
  }

  async interceptStartSkillDraftRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 201,
    files = [{ path: "SKILL.md", content: "# My tool" }],
  }: {
    skillId?: string;
    status?: number;
    files?: { path: string; content: string }[];
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/draft*`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail: "Unable to start draft" })
            : JSON.stringify({
                skill_id: skillId,
                files,
                description: null,
                required_providers: [],
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:00:00Z",
              }),
      });
    });
  }

  async interceptCreateSkillRequest({
    status = 201,
    detail = "Unable to create skill",
    skill,
  }: {
    status?: number;
    detail?: string;
    skill?: Record<string, unknown>;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/skills", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail })
            : JSON.stringify(skill ?? { ...mockCustomSkill, id: "cccccccc-1111-4ccc-8ccc-cccccccccccc" }),
      });
    });
  }

  async interceptUpdateSkillRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 200,
    detail = "Unable to update skill",
    skill,
  }: {
    skillId?: string;
    status?: number;
    detail?: string;
    skill?: Record<string, unknown>;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status >= 400 ? JSON.stringify({ detail }) : JSON.stringify(skill ?? mockCustomSkill),
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

  async interceptGetSkillVersionsRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 200,
    versions = [
      { version: 1, created_by: null, created_at: "2026-01-01T00:00:00Z", is_pinned_by_agent: false },
    ],
    scope = "organization",
    agentId = MOCK_AGENT_ID,
  }: {
    skillId?: string;
    status?: number;
    versions?: Record<string, unknown>[];
    scope?: "organization" | "platform" | "agent";
    agentId?: string;
  } = {}) {
    const path = scope === "platform"
      ? `**/api/v1/platform/skills/${skillId}/versions`
      : scope === "agent"
        ? `**/api/v1/organizations/*/agents/${agentId}/skills/${skillId}/versions`
        : `**/api/v1/organizations/*/skills/${skillId}/versions`;
    await this.page.route(path, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status >= 400 ? JSON.stringify({ detail: "Unable to load versions" }) : JSON.stringify(versions),
      });
    });
  }

  async interceptGetSkillVersionRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    version = 1,
    status = 200,
    files = [{ path: "SKILL.md", content: "# My tool" }],
  }: {
    skillId?: string;
    version?: number;
    status?: number;
    files?: { path: string; content: string }[];
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/versions/${version}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail: "Unable to load version" })
            : JSON.stringify({
                version,
                created_by: null,
                created_at: "2026-01-01T00:00:00Z",
                is_pinned_by_agent: false,
                files,
              }),
      });
    });
  }

  async interceptUpdateSkillDraftRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 200,
    files = [{ path: "SKILL.md", content: "# My tool" }],
  }: {
    skillId?: string;
    status?: number;
    files?: { path: string; content: string }[];
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/draft*`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail: "Unable to update draft" })
            : JSON.stringify({
                skill_id: skillId,
                files,
                description: null,
                required_providers: [],
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:00:00Z",
              }),
      });
    });
  }

  async interceptDiscardSkillDraftRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 204,
  }: {
    skillId?: string;
    status?: number;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/draft*`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status >= 400 ? JSON.stringify({ detail: "Unable to discard draft" }) : "",
      });
    });
  }

  async interceptPublishSkillDraftRequest({
    skillId = MOCK_CUSTOM_SKILL_ID,
    status = 201,
    skill,
  }: {
    skillId?: string;
    status?: number;
    skill?: Record<string, unknown>;
  } = {}) {
    await this.page.route(`**/api/v1/organizations/*/skills/${skillId}/draft/publish`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body:
          status >= 400
            ? JSON.stringify({ detail: "Unable to publish draft" })
            : JSON.stringify(skill ?? { ...mockCustomSkill, version: 2, hasDraft: false }),
      });
    });
  }
}
