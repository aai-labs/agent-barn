import { Page } from "@playwright/test";

export const MOCK_PLATFORM_TEMPLATE_ID = "11111111-1111-4111-8111-111111111111";
export const MOCK_PLATFORM_TEMPLATE_V1_ID = "22222222-2222-4222-8222-222222222222";
export const MOCK_PLATFORM_TEMPLATE_SLUG = "code-reviewer";
export const MOCK_PLATFORM_TEMPLATE_SKILL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

export const mockPlatformTemplateLineages = [
  {
    template_slug: MOCK_PLATFORM_TEMPLATE_SLUG,
    template_name: "Code Reviewer",
    latest_published_version: 2,
    has_draft: true,
  },
  {
    template_slug: "general-purpose",
    template_name: "General Purpose",
    latest_published_version: 1,
    has_draft: false,
  },
];

export const mockPlatformTemplateDraft = {
  id: MOCK_PLATFORM_TEMPLATE_ID,
  template_slug: MOCK_PLATFORM_TEMPLATE_SLUG,
  template_name: "Code Reviewer",
  description: "Reviews changes for correctness and maintainability.",
  soul_md: "You are a careful code reviewer.",
  identity_md: "# Identity\n\nCode Reviewer",
  user_md: "# User\n\nThe developer requesting a review.",
  tools_md: "# Tools\n\nUse the repository tools.",
  agents_md: "# Agents\n\nNo child agents.",
  boot_md: "# Boot\n\nStart by reading the request.",
  bootstrap_md: "# Bootstrap\n\nLoad the repository context.",
  heartbeat_md: "# Heartbeat\n\nRemain available.",
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
  required_skills: [
    {
      id: MOCK_PLATFORM_TEMPLATE_SKILL_ID,
      organization_id: null,
      name: "github",
      source: "aai_cli",
      required_providers: ["github"],
      tools_pointer: null,
      group_key: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
};

export const mockPlatformTemplatePublished = {
  id: MOCK_PLATFORM_TEMPLATE_ID,
  organization_id: null,
  template_slug: MOCK_PLATFORM_TEMPLATE_SLUG,
  template_name: "Code Reviewer",
  template_source: "pre-defined",
  forked_from_platform_template_id: null,
  fork_baseline_platform_template_id: null,
  version: 2,
  description: "Reviews changes for correctness and maintainability.",
  soul_md: "You are a careful code reviewer.",
  identity_md: "# Identity\n\nCode Reviewer",
  user_md: "# User\n\nThe developer requesting a review.",
  tools_md: "# Tools\n\nUse the repository tools.",
  agents_md: "# Agents\n\nNo child agents.",
  boot_md: "# Boot\n\nStart by reading the request.",
  bootstrap_md: "# Bootstrap\n\nLoad the repository context.",
  heartbeat_md: "# Heartbeat\n\nRemain available.",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
  required_skills: [
    {
      id: MOCK_PLATFORM_TEMPLATE_SKILL_ID,
      organization_id: null,
      name: "github",
      source: "aai_cli",
      required_providers: ["github"],
      tools_pointer: null,
      group_key: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  in_use: false,
};

export const mockPlatformTemplatePublishedV1 = {
  ...mockPlatformTemplatePublished,
  id: MOCK_PLATFORM_TEMPLATE_V1_ID,
  version: 1,
  soul_md: "You are a careful code reviewer from version one.",
  updated_at: "2026-07-03T00:00:00Z",
};

export const mockPlatformTemplateVersions = [
  mockPlatformTemplatePublished,
  mockPlatformTemplatePublishedV1,
];

export class PlatformTemplateDataSupport {
  constructor(private page: Page) {}

  async interceptGetLineages({
    status = 200,
    detail = "Unable to load platform templates",
    body = mockPlatformTemplateLineages,
  }: { status?: number; detail?: string; body?: unknown } = {}) {
    await this.page.route("**/api/v1/platform/templates", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : body),
      });
    });
  }

  async interceptGetGlobalSkills({ body = [] }: { body?: unknown } = {}) {
    await this.page.route("**/api/v1/platform/skills", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptGetPublished({
    slug = MOCK_PLATFORM_TEMPLATE_SLUG,
    body = mockPlatformTemplatePublished,
  }: { slug?: string; body?: unknown } = {}) {
    await this.page.route(
      `**/api/v1/platform/templates/${slug}`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      },
    );
  }

  async interceptGetVersions({
    slug = MOCK_PLATFORM_TEMPLATE_SLUG,
    body = mockPlatformTemplateVersions,
  }: { slug?: string; body?: unknown } = {}) {
    await this.page.route(
      `**/api/v1/platform/templates/${slug}/versions`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      },
    );
  }

  async interceptGetDraft({ body = mockPlatformTemplateDraft }: { body?: unknown } = {}) {
    await this.page.route(
      `**/api/v1/platform/templates/${MOCK_PLATFORM_TEMPLATE_SLUG}/draft`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      },
    );
  }

  async interceptUpdateDraft() {
    await this.page.route(
      `**/api/v1/platform/templates/${MOCK_PLATFORM_TEMPLATE_SLUG}/draft`,
      async (route) => {
        if (route.request().method() !== "PATCH") {
          await route.fallback();
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockPlatformTemplateDraft) });
      },
    );
  }

  async interceptStartDraft({
    slug = MOCK_PLATFORM_TEMPLATE_SLUG,
    body = mockPlatformTemplateDraft,
  }: { slug?: string; body?: unknown } = {}) {
    await this.page.route(
      `**/api/v1/platform/templates/${slug}/draft*`,
      async (route) => {
        if (route.request().method() !== "POST") {
          await route.fallback();
          return;
        }
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
      },
    );
  }
}
