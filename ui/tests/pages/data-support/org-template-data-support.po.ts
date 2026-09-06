import { Page } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";

export const MOCK_ORG_TEMPLATE_KEY = "my-custom";
export const MOCK_ORG_TEMPLATE_ID = "55555555-5555-4555-8555-555555555551";
export const MOCK_ORG_TEMPLATE_V1_ID = "55555555-5555-4555-8555-555555555552";
export const MOCK_ORG_FORK_KEY = "general-purpose";
export const MOCK_ORG_TEMPLATE_SKILL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

const ORG_BASE = `**/api/v1/organizations/${TEST_ORG_ID}/templates`;

export const mockOrgTemplateLineages = [
  {
    template_key: MOCK_ORG_FORK_KEY,
    template_name: "General Purpose",
    latest_published_version: 1,
    has_draft: false,
    template_source: "pre-defined",
    is_fork: false,
    platform_update_available: false,
    in_use: false,
  },
  {
    template_key: MOCK_ORG_TEMPLATE_KEY,
    template_name: "My Custom",
    latest_published_version: 2,
    has_draft: true,
    template_source: "custom",
    is_fork: false,
    platform_update_available: false,
    in_use: false,
  },
];

export const mockOrgTemplateDraft = {
  id: MOCK_ORG_TEMPLATE_ID,
  organization_id: TEST_ORG_ID,
  template_key: MOCK_ORG_TEMPLATE_KEY,
  template_name: "My Custom",
  template_source: "custom",
  forked_from_platform_template_id: null,
  fork_baseline_platform_template_id: null,
  fork_baseline_platform_version: null,
  description: "An organization-authored template.",
  soul_md: "You are our in-house helper.",
  identity_md: "# Identity\n\nMy Custom",
  user_md: "# User\n\nOur team.",
  tools_md: "# Tools\n\nUse the org tools.",
  agents_md: "# Agents\n\nNo child agents.",
  boot_md: "# Boot\n\nStart here.",
  bootstrap_md: "# Bootstrap\n\nLoad org context.",
  heartbeat_md: "# Heartbeat\n\nStay available.",
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
  required_skills: [],
};

export const mockOrgTemplatePublished = {
  id: MOCK_ORG_TEMPLATE_ID,
  organization_id: TEST_ORG_ID,
  template_key: MOCK_ORG_TEMPLATE_KEY,
  template_name: "My Custom",
  template_source: "custom",
  forked_from_platform_template_id: null,
  fork_baseline_platform_template_id: null,
  fork_baseline_platform_version: null,
  platform_update_available: false,
  version: 2,
  description: "An organization-authored template.",
  soul_md: "You are our in-house helper.",
  identity_md: "# Identity\n\nMy Custom",
  user_md: "# User\n\nOur team.",
  tools_md: "# Tools\n\nUse the org tools.",
  agents_md: "# Agents\n\nNo child agents.",
  boot_md: "# Boot\n\nStart here.",
  bootstrap_md: "# Bootstrap\n\nLoad org context.",
  heartbeat_md: "# Heartbeat\n\nStay available.",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
  required_skills: [],
  in_use: false,
};

export const mockOrgTemplatePublishedV1 = {
  ...mockOrgTemplatePublished,
  id: MOCK_ORG_TEMPLATE_V1_ID,
  version: 1,
  soul_md: "You are our in-house helper, version one.",
  updated_at: "2026-07-03T00:00:00Z",
};

export const mockOrgTemplateVersions = [mockOrgTemplatePublished, mockOrgTemplatePublishedV1];

export class OrgTemplateDataSupport {
  constructor(private page: Page) {}

  async interceptGetLineages({
    status = 200,
    detail = "Unable to load templates",
    body = mockOrgTemplateLineages,
  }: { status?: number; detail?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/lineages`, async (route) => {
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

  async interceptGetPublished({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplatePublished,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptGetVersions({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplateVersions,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/versions`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptGetDraft({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    status = 200,
    body = mockOrgTemplateDraft,
  }: { templateKey?: string; status?: number; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/draft`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail: "No draft" } : body),
      });
    });
  }

  async interceptStartDraft({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplateDraft,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/draft*`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptUpdateDraft({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplateDraft,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/draft`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptDiscardDraft({ templateKey = MOCK_ORG_TEMPLATE_KEY }: { templateKey?: string } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/draft`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 204, body: "" });
    });
  }

  async interceptPublishDraft({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplatePublished,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/draft/publish`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptCreateDraft({ body = mockOrgTemplateDraft }: { body?: unknown } = {}) {
    await this.page.route(ORG_BASE, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptDeleteTemplate({ templateKey = MOCK_ORG_TEMPLATE_KEY }: { templateKey?: string } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}`, async (route) => {
      if (route.request().method() !== "DELETE") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 204, body: "" });
    });
  }

  async interceptPlatformUpdate({
    templateKey = MOCK_ORG_TEMPLATE_KEY,
    body = mockOrgTemplatePublished,
  }: { templateKey?: string; body?: unknown } = {}) {
    await this.page.route(`${ORG_BASE}/${templateKey}/platform-update`, async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(body) });
    });
  }

  async interceptGetOrgSkills({ items = [] }: { items?: unknown[] } = {}) {
    const body = { page: 1, page_size: 200, total: items.length, items };
    await this.page.route(`**/api/v1/organizations/${TEST_ORG_ID}/skills*`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
  }
}
