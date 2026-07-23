import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentDetailPage } from "../pages/agent-detail-page.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import {
  MOCK_AGENT_ID,
  MOCK_OWNER_ROLE_ID,
  mockAgent,
  mockAssignedMember,
  mockShareSettingsAll,
  mockShareSettingsRestricted,
} from "../pages/data-support/agent-data-support.po";
import { ORG_B_ID } from "../pages/data-support/organization-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const GRACE_MEMBER = {
  user_id: "99999999-9999-4999-8999-999999999999",
  email: "grace@example.com",
  full_name: "Grace Hopper",
  role: "MEMBER",
  is_pending: false,
};

const PENDING_MEMBER = {
  user_id: "aaaaaaaa-1111-4aaa-8aaa-111111111111",
  email: "pending@example.com",
  full_name: "Pending Person",
  role: "MEMBER",
  is_pending: true,
};

const ORG_OWNER_MEMBER = {
  user_id: "bbbbbbbb-2222-4bbb-8bbb-222222222222",
  email: "owner@example.com",
  full_name: "Org Owner",
  role: "OWNER",
  is_pending: false,
};

test.describe("Agent sharing", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  let data: DataSupport;
  let agentDetailPage: AgentDetailPage;

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    agentDetailPage = new AgentDetailPage(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest();
    await data.agents.interceptGetAgentTemplateRequest();
    await data.agents.interceptGetShareRolesRequest();
    await data.agents.interceptGetAgentShareRequest();
    await data.organizations.interceptGetMembers({ members: [] });

    await agentDetailPage.goto(MOCK_AGENT_ID);
  });

  test("Share button is visible with agent.access.manage, opens the dialog, and loads one share snapshot", async () => {
    await expect(agentDetailPage.shareButton()).toBeVisible();

    await agentDetailPage.shareButton().click();

    await expect(agentDetailPage.shareDialog()).toBeVisible();
    await expect(
      agentDetailPage.shareDialog().getByText(mockAssignedMember.email),
    ).toBeVisible();
    await expect(agentDetailPage.generalAccessSelect()).toHaveValue("restricted");
    // Nothing changed yet — Save should stay disabled rather than fire a no-op request.
    await expect(agentDetailPage.saveShareButton()).toBeDisabled();
  });

  test("Share button is hidden without agent.access.manage (permission-aware visibility)", async () => {
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: ["agent.read", "agent.update", "activity.read"],
      },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(agentDetailPage.shareButton()).toHaveCount(0);
  });

  test("Owner can search Members by name/email, stage a grant, and Save sends one PUT with the full snapshot", async ({
    page,
  }) => {
    await data.organizations.interceptGetMembers({ members: [GRACE_MEMBER] });
    let putBody: unknown;
    await page.route(`**/api/v1/agents/${MOCK_AGENT_ID}/share`, async (route) => {
      if (route.request().method() !== "PUT") {
        await route.fallback();
        return;
      }
      putBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockShareSettingsRestricted),
      });
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("grace");
    await expect(
      agentDetailPage.shareDialog().getByText(GRACE_MEMBER.email),
    ).toBeVisible();

    await agentDetailPage.addCandidateButton(GRACE_MEMBER.email).click();
    await expect(agentDetailPage.memberRoleSelect(GRACE_MEMBER.email)).toBeVisible();

    await agentDetailPage.saveShareButton().click();

    await expect(page.getByText(/sharing updated/i)).toBeVisible();
    // One PUT call carrying the complete desired assignment list — the existing
    // Member plus the newly staged one — not a separate call per recipient. The
    // request body is on the wire (snake_case), not the camelCase JS shape.
    expect(putBody).toMatchObject({
      assignments: expect.arrayContaining([
        expect.objectContaining({ user_id: mockAssignedMember.user_id }),
        expect.objectContaining({ user_id: GRACE_MEMBER.user_id }),
      ]),
    });
    expect((putBody as { assignments: unknown[] }).assignments).toHaveLength(2);
  });

  test("Searching a pending Member or an Organization Owner shows why they can't be added directly", async () => {
    await data.organizations.interceptGetMembers({
      members: [PENDING_MEMBER, ORG_OWNER_MEMBER],
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("e");

    await expect(
      agentDetailPage.shareDialog().getByText(/pending invite/i),
    ).toBeVisible();
    await expect(
      agentDetailPage.shareDialog().getByText(/owner .* full access already/i),
    ).toBeVisible();
    await expect(
      agentDetailPage.addCandidateButton(PENDING_MEMBER.email),
    ).toHaveCount(0);
    await expect(
      agentDetailPage.addCandidateButton(ORG_OWNER_MEMBER.email),
    ).toHaveCount(0);
  });

  test("Searching for a Member who already has direct access shows 'Already has access' instead of a duplicate row", async () => {
    await data.organizations.interceptGetMembers({
      members: [
        {
          user_id: mockAssignedMember.user_id,
          email: mockAssignedMember.email,
          full_name: mockAssignedMember.full_name,
          role: "MEMBER",
          is_pending: false,
        },
      ],
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("ada");

    await expect(
      agentDetailPage.shareDialog().getByText(/already has access/i),
    ).toBeVisible();
    await expect(
      agentDetailPage.addCandidateButton(mockAssignedMember.email),
    ).toHaveCount(0);
  });

  test("Search results are capped so a broad query can't dump the whole Organization into the dialog", async ({
    page,
  }) => {
    const manyMembers = Array.from({ length: 25 }, (_, i) => ({
      user_id: `cccccccc-0000-4ccc-8ccc-${String(i).padStart(12, "0")}`,
      email: `member${i}@example.com`,
      full_name: `Member Number ${i}`,
      role: "MEMBER",
      is_pending: false,
    }));
    let requestedLimit: string | null = null;
    await page.route("**/api/v1/organizations/*/members*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const url = new URL(route.request().url());
      requestedLimit = url.searchParams.get("limit");
      const limit = requestedLimit ? Number(requestedLimit) : undefined;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(limit ? manyMembers.slice(0, limit) : manyMembers),
      });
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("member");

    await expect(
      agentDetailPage.shareDialog().getByText(/showing the first 8 matches/i),
    ).toBeVisible();
    await expect(
      agentDetailPage.addCandidateButton("member0@example.com"),
    ).toBeVisible();
    // Bounded by a server-side `limit`, not fetched in full and truncated client-side.
    expect(requestedLimit).toBe("9");
  });

  test("Searching for a Member just removed (not yet saved) finds them to restore access", async () => {
    // The share snapshot loaded at open time still lists this Member — removing them
    // only edits the local draft. Re-searching for them must reflect the draft's
    // current state (not assigned), not the last-fetched snapshot.
    await data.organizations.interceptGetMembers({
      members: [
        {
          user_id: mockAssignedMember.user_id,
          email: mockAssignedMember.email,
          full_name: mockAssignedMember.full_name,
          role: "MEMBER",
          is_pending: false,
        },
      ],
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.removeMember(mockAssignedMember.email);
    await expect(
      agentDetailPage.memberRoleSelect(mockAssignedMember.email),
    ).toHaveCount(0);

    await agentDetailPage.shareSearchInput().fill("ada");
    await expect(
      agentDetailPage.shareDialog().getByText(mockAssignedMember.email),
    ).toBeVisible();
    await agentDetailPage.addCandidateButton(mockAssignedMember.email).click();

    await expect(
      agentDetailPage.memberRoleSelect(mockAssignedMember.email),
    ).toBeVisible();
  });

  test("Owner can change a Member's access role, including an Owner-level (onward sharing) role", async ({
    page,
  }) => {
    await data.agents.interceptPutAgentShareRequest();

    await agentDetailPage.shareButton().click();

    // The role catalogue's capability breakdown (incl. the sensitive-permission
    // callout for Owner) lives behind the "?" help button, not inline per select.
    await agentDetailPage.shareHelpButton().click();
    await expect(
      agentDetailPage.shareHelpDialog().getByText(/can delete this agent and manage/i),
    ).toBeVisible();
    await agentDetailPage.shareHelpDialog().getByRole("button", { name: "Close" }).click();

    await agentDetailPage
      .memberRoleSelect(mockAssignedMember.email)
      .selectOption(MOCK_OWNER_ROLE_ID);
    await agentDetailPage.saveShareButton().click();

    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Removing a direct grant explains the Member keeps General access, then Save applies it", async ({
    page,
  }) => {
    await data.agents.interceptGetAgentShareRequest({ body: mockShareSettingsAll });
    await data.agents.interceptPutAgentShareRequest();

    await agentDetailPage.shareButton().click();
    await expect(agentDetailPage.generalAccessSelect()).toHaveValue("all");

    await agentDetailPage.removeMember(mockAssignedMember.email);

    // Tied to this specific removal via a toast, not a persistent banner — a banner
    // has nothing to anchor to once the list of direct grants is empty.
    await expect(
      page.getByText(/still has .* access via general access/i),
    ).toBeVisible();
    await expect(
      agentDetailPage.memberRoleSelect(mockAssignedMember.email),
    ).toHaveCount(0);

    await agentDetailPage.saveShareButton().click();
    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Owner can stage General access as All Organization Members, then Save applies it", async ({
    page,
  }) => {
    await data.agents.interceptPutAgentShareRequest({ body: mockShareSettingsAll });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.generalAccessSelect().selectOption("all");

    await expect(agentDetailPage.generalAccessRoleSelect()).toBeVisible();
    await expect(
      page.getByText(/applies automatically to current and future accepted members/i),
    ).toBeVisible();

    await agentDetailPage.saveShareButton().click();

    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Save errors leave the draft in place for correction, without implying partial success", async ({
    page,
  }) => {
    await data.organizations.interceptGetMembers({ members: [GRACE_MEMBER] });
    await data.agents.interceptPutAgentShareRequest({
      status: 409,
      detail: "Agent share settings were updated by someone else — reload and retry",
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("grace");
    await agentDetailPage.addCandidateButton(GRACE_MEMBER.email).click();
    await agentDetailPage.saveShareButton().click();

    await expect(
      page.getByText(/updated by someone else — reload and retry/i),
    ).toBeVisible();
    // The dialog stays open with the staged edit intact so the user can retry.
    await expect(agentDetailPage.shareDialog()).toBeVisible();
    await expect(agentDetailPage.memberRoleSelect(GRACE_MEMBER.email)).toBeVisible();
  });

  test("A concealed (404) Agent shows an inline error instead of a broken dialog", async () => {
    await data.agents.interceptGetAgentShareRequest({
      status: 404,
      detail: "Agent not found",
    });

    await agentDetailPage.shareButton().click();

    await expect(
      agentDetailPage.shareDialog().getByText(/couldn't load sharing settings/i),
    ).toBeVisible();
  });

  test("Sharing-relevant Agent data does not leak across Organizations", async ({
    page,
  }) => {
    // The share snapshot, share roles, and org-member search all live under the same
    // "agents" (and org-scoped) query-key groups that are dropped wholesale on a
    // genuine in-app org switch (see organization-provider.tsx's ORG_SCOPED_QUERY_KEYS
    // eviction). Exercise that same switch here — a page.goto would reload the whole
    // app and trivially "pass" without touching the eviction logic Share depends on.
    await data.organizations.interceptListOrganizations({
      items: [
        {
          id: TEST_ORG_ID,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "AAI Labs",
          description: "Starter organization",
          is_default: false,
          owner_email: "owner@example.com",
          owner_name: "Grace Hopper",
        },
        {
          id: ORG_B_ID,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "Globex",
          description: "Second organization",
          is_default: false,
          owner_email: "hank@globex.com",
          owner_name: "Hank Scorpio",
        },
      ],
    });
    await data.organizations.interceptGetOrganization();
    await page.route("**/api/v1/agents?*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      const orgHeader = await route.request().headerValue("x-organization-id");
      const agent = orgHeader === ORG_B_ID ? { ...mockAgent, name: "Aria" } : mockAgent;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ page: 1, page_size: 50, total: 1, items: [agent] }),
      });
    });

    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await expect(page.getByText("Maya")).toBeVisible();

    const switcher = page.locator('button[aria-haspopup="listbox"]');
    await switcher.click();
    await page.getByRole("listbox").getByRole("option", { name: /globex/i }).click();

    await expect(page).toHaveURL(new RegExp(ORG_B_ID));
    await expect(page.getByText("Aria")).toBeVisible();
    await expect(page.getByText("Maya")).not.toBeVisible();
  });
});
