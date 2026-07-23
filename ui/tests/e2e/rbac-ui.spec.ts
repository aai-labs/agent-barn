import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  MOCK_AGENT_ID,
  mockAgent,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { RbacUiPage } from "../pages/rbac-ui.po";

const MEMBER_USER_ID = "77777777-7777-4777-8777-777777777777";

function memberContext(
  userId = MEMBER_USER_ID,
  role: "ADMIN" | "MEMBER" | "OWNER" = "MEMBER",
) {
  const organization = {
    id: TEST_ORG_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    is_default: false,
    owner_email: "owner@example.com",
    owner_name: "Owner",
  };
  return {
    id: userId,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    full_name: "Creator Member",
    email: "creator@example.com",
    is_superuser: false,
    email_verified_at: "2024-01-01T00:00:00Z",
    organization_users: [
      {
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        user_id: userId,
        organization_id: TEST_ORG_ID,
        role,
        organization,
      },
    ],
  };
}

test.describe("RBAC-aware Agent controls", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("uses effective actions instead of role names for Agent controls", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: ["agent.read", "activity.read"],
      },
    });
    await data.agents.interceptGetAgentTemplateRequest();

    await rbac.gotoAgent(MOCK_AGENT_ID);

    await expect(page.getByRole("heading", { name: "Maya" })).toBeVisible();
    await expect(rbac.agentAction(/pause/i)).toHaveCount(0);
    await expect(rbac.agentAction(/configure/i)).toHaveCount(0);
    await expect(rbac.agentAction(/^access$/i)).toHaveCount(0);
    await expect(rbac.agentAction("Conversations")).toBeVisible();
  });

  test("Editor controls are shown without Owner-only deletion", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: [
          "agent.read",
          "agent.update",
          "agent.lifecycle.manage",
          "agent.secret.manage",
          "activity.read",
          "cost.read",
        ],
      },
    });
    await data.agents.interceptGetAgentTemplateRequest();

    await rbac.gotoAgent(MOCK_AGENT_ID);

    await expect(rbac.agentAction(/pause/i)).toBeVisible();
    await expect(rbac.agentAction(/configure/i)).toBeVisible();
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?configTab=danger`,
    );
    await expect(page.getByRole("button", { name: "Retire agent" })).toHaveCount(0);
    await expect(rbac.agentAction(/^access$/i)).toHaveCount(0);
  });

  test("Owner deletion is available without exposing sharing UI", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ body: mockAgent });
    await data.agents.interceptGetAgentTemplateRequest();

    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?configTab=danger`,
    );

    await expect(page.getByRole("button", { name: "Retire agent" })).toBeVisible();
    await expect(rbac.agentAction(/^access$/i)).toHaveCount(0);
  });

  test("inaccessible Agents use normal not-found handling", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ status: 404 });

    await rbac.gotoAgent(MOCK_AGENT_ID);

    await expect(page.getByText("We couldn't load this agent")).toBeVisible();
    await expect(rbac.agentAction(/configure/i)).toHaveCount(0);
    await expect(rbac.agentAction(/^access$/i)).toHaveCount(0);
  });
});

test.describe("RBAC-aware organization controls", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("Admin cannot promote Members or control another Admin", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    const actingAdminId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: memberContext(actingAdminId, "ADMIN"),
    });
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptGetMembers({
      members: [
        {
          user_id: "44444444-4444-4444-8444-444444444444",
          email: "owner@example.com",
          full_name: "Owner User",
          role: "OWNER",
          is_pending: false,
        },
        {
          user_id: actingAdminId,
          email: "acting-admin@example.com",
          full_name: "Acting Admin",
          role: "ADMIN",
          is_pending: false,
        },
        {
          user_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          email: "other-admin@example.com",
          full_name: "Other Admin",
          role: "ADMIN",
          is_pending: false,
        },
        {
          user_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          email: "member@example.com",
          full_name: "Ordinary Member",
          role: "MEMBER",
          is_pending: false,
        },
      ],
    });

    await rbac.gotoMembers();

    await expect(
      rbac.memberRow("Other Admin").getByRole("button", { name: "Member actions" }),
    ).toHaveCount(0);

    await rbac.openMemberActions("Ordinary Member");
    await expect(page.getByRole("button", { name: "Make admin" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Remove from org" })).toBeVisible();
  });
});

test.describe("RBAC-aware shared resource controls", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("Member can inspect Templates and Skills without mutation controls", async ({ page }) => {
    const data = new DataSupport(page);
    const rbac = new RbacUiPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetTemplateVersionsRequest();
    await data.skills.interceptGetSkillsRequest();

    await rbac.gotoSettings();

    await rbac.openSettingsSection("Templates");
    await expect(rbac.newTemplateButton()).toHaveCount(0);
    await rbac.openTemplate("My Custom");
    await expect(page.getByRole("heading", { name: "My Custom" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit template" })).toHaveCount(0);
    await rbac.closeTemplate();

    await rbac.openSettingsSection("Skills");
    await expect(rbac.newSkillButton()).toHaveCount(0);
    await rbac.openSkill("my-tool");
    await expect(page.getByRole("button", { name: "Edit skill" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
  });
});
