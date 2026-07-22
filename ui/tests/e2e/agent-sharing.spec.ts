import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentDetailPage } from "../pages/agent-detail-page.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import {
  MOCK_AGENT_ID,
  MOCK_OWNER_ROLE_ID,
  mockAgent,
  mockAssignedMember,
  mockEligibleCandidate,
  mockGeneralAccessAll,
} from "../pages/data-support/agent-data-support.po";
import { ORG_B_ID } from "../pages/data-support/organization-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

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
    await data.agents.interceptGetAccessRolesRequest();
    await data.agents.interceptGetAgentAccessListRequest();
    await data.agents.interceptGetEligibleAgentAccessRequest();
    await data.agents.interceptGetGeneralAccessRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
  });

  test("Share button is visible with agent.access.manage and opens the dialog", async () => {
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

  test("Owner can search Members, stage a grant, and Save applies it", async ({
    page,
  }) => {
    await data.agents.interceptGrantAgentAccessRequest();

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("grace");
    await expect(
      agentDetailPage.shareDialog().getByText(mockEligibleCandidate.email),
    ).toBeVisible();

    await agentDetailPage.addCandidateButton(mockEligibleCandidate.email).click();

    // Staged locally — no network call and the candidate now shows as a direct grant.
    await expect(
      agentDetailPage.memberRoleSelect(mockEligibleCandidate.email),
    ).toBeVisible();

    await agentDetailPage.saveShareButton().click();

    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Owner can change a Member's access role, including an Owner-level (onward sharing) role", async ({
    page,
  }) => {
    await data.agents.interceptChangeAgentAccessRoleRequest();

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
    await data.agents.interceptGetGeneralAccessRequest({ body: mockGeneralAccessAll });
    await data.agents.interceptRevokeAgentAccessRequest();

    await agentDetailPage.shareButton().click();
    await expect(agentDetailPage.generalAccessSelect()).toHaveValue("all");

    await agentDetailPage.removeMember(mockAssignedMember.email);

    await expect(
      page.getByText(new RegExp("still get(?:s)? .* access via general access", "i")),
    ).toBeVisible();
    await expect(
      agentDetailPage.memberRoleSelect(mockAssignedMember.email),
    ).toHaveCount(0);

    await agentDetailPage.saveShareButton().click();
    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Searching for a Member just removed (not yet saved) finds them to restore access", async () => {
    // The eligible-access endpoint reflects server truth, which still has this Member
    // assigned until Save — the search must merge in staged-for-removal Members
    // locally rather than relying solely on that (stale, from this session's view) list.
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
    // Restored to the original role with nothing else changed — a true no-op — so
    // Save has nothing to send.
    await expect(agentDetailPage.saveShareButton()).toBeDisabled();
  });

  test("Owner can stage General access as All Organization Members, then Save applies it", async ({
    page,
  }) => {
    await data.agents.interceptSetGeneralAccessRequest();

    await agentDetailPage.shareButton().click();
    await agentDetailPage.generalAccessSelect().selectOption("all");

    await expect(agentDetailPage.generalAccessRoleSelect()).toBeVisible();
    await expect(
      page.getByText(/applies automatically to current and future accepted members/i),
    ).toBeVisible();

    await agentDetailPage.saveShareButton().click();

    await expect(page.getByText(/sharing updated/i)).toBeVisible();
  });

  test("Grant errors surface the server's message (e.g. conflicting update)", async ({
    page,
  }) => {
    await data.agents.interceptGrantAgentAccessRequest({
      status: 409,
      detail: "Agent Access already exists with a different role",
    });

    await agentDetailPage.shareButton().click();
    await agentDetailPage.shareSearchInput().fill("grace");
    await agentDetailPage.addCandidateButton(mockEligibleCandidate.email).click();
    await agentDetailPage.saveShareButton().click();

    await expect(
      page.getByText(/agent access already exists with a different role/i),
    ).toBeVisible();
    // The dialog stays open with the staged edit intact so the user can retry.
    await expect(agentDetailPage.shareDialog()).toBeVisible();
  });

  test("A concealed (404) Agent shows an inline error instead of a broken dialog", async () => {
    await data.agents.interceptGetGeneralAccessRequest({
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
    // Sharing queries (access, eligible, general-access) all live under the same
    // "agents" query-key group as the Agent list, and that group is dropped wholesale
    // on a genuine in-app org switch (see organization-provider.tsx's
    // ORG_SCOPED_QUERY_KEYS eviction). Exercise that same switch here — a page.goto
    // would reload the whole app and trivially "pass" without ever touching the
    // eviction logic the Share dialog depends on.
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
