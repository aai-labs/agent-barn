import { Page } from "@playwright/test";

export const MOCK_PLATFORM_SKILL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const MOCK_CUSTOM_SKILL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

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
    await this.page.route("**/api/v1/skills", async (route) => {
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
            : (body ?? [mockPlatformSkill, mockCustomSkill]),
        ),
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
    await this.page.route(`**/api/v1/skills/${skillId}`, async (route) => {
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