import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { AgentAnomaliesPage } from "../pages/agent-anomalies-page.po";
import { mockAgent, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { mockAnomaly, mockNormalBehaviour } from "../pages/data-support/anomaly-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.use({ storageState: { cookies: [], origins: [] } });

type Json = Record<string, unknown>;

function contextWithRole(role: string) {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({ ...membership, role })),
  };
}

async function openTab(
  page: Page,
  { role = "OWNER", anomalies = [], normal }: { role?: string; anomalies?: Json[]; normal?: Json } = {},
) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: contextWithRole(role) });
  await data.users.interceptGetOrganizationsRequest();
  await data.agents.interceptGetAgentRequest({
    body: { ...mockAgent, name: "Sally", allowed_actions: mockAgentAllowedActions },
  });
  await data.agents.interceptGetAgentHealthRequest();
  await data.agents.interceptGetConversationChannelsRequest();
  const mock = await data.anomalies.interceptAgent({ anomalies, normal: normal ?? mockNormalBehaviour() });
  const anomaliesPage = new AgentAnomaliesPage(page);
  await anomaliesPage.goto();
  return { mock, anomaliesPage };
}

test.describe("Agent · Unusual activity", () => {
  test("Owners and Admins find the tab under Health", async ({ page }) => {
    const { anomaliesPage } = await openTab(page);

    await expect(anomaliesPage.tab()).toBeVisible();
  });

  test("a Member who owns the Agent does not see the tab", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, { role: "MEMBER" });

    await expect(page.getByRole("complementary").getByRole("link", { name: "Overview" })).toBeVisible();
    await expect(anomaliesPage.tab()).toHaveCount(0);
  });

  test("a spike names what jumped, how far, and what is usual", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, { anomalies: [mockAnomaly()] });

    const anomaly = anomaliesPage.anomalies().first();
    await expect(anomaly).toContainText("Tool calls per hour");
    await expect(anomaly).toContainText("400");
    await expect(anomaly).toContainText("usually 100");
    await expect(anomaly).toContainText("Ongoing");
  });

  test("failing model calls read as a share of the Agent's model calls", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, {
      anomalies: [mockAnomaly({ signal: "LLM_ERROR_RATE", observed_value: 0.8, usual_value: 0.05, threshold: 0.3 })],
    });

    const anomaly = anomaliesPage.anomalies().first();
    await expect(anomaly).toContainText("Failed model calls");
    await expect(anomaly).toContainText("80%");
    await expect(anomaly).toContainText("usually 5%");
  });

  test("a first use names the destination and says where it was seen", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, {
      anomalies: [
        mockAnomaly({
          signal: "NEW_DESTINATION",
          subject: "new.example.org",
          observed_value: 1,
          usual_value: null,
          threshold: null,
          ended_at: "2026-11-16T09:15:00Z",
        }),
      ],
    });

    const anomaly = anomaliesPage.anomalies().first();
    await expect(anomaly).toContainText("New destination");
    await expect(anomaly).toContainText("new.example.org");
    await expect(anomaliesPage.anomalyList()).toContainText("seen in tool calls");
  });

  test("older Anomalies than the first page load on request", async ({ page }) => {
    const anomalies = Array.from({ length: 51 }, (_, index) =>
      mockAnomaly({ subject: `host-${index}.example`, signal: "NEW_DESTINATION", usual_value: null, threshold: null }),
    );
    const { anomaliesPage } = await openTab(page, { anomalies });
    await expect(anomaliesPage.anomalies()).toHaveCount(50);

    await anomaliesPage.anomalyList().getByRole("button", { name: "Load more" }).click();

    await expect(anomaliesPage.anomalies()).toHaveCount(51);
    await expect(anomaliesPage.anomalies().last()).toContainText("host-50.example");
    await expect(anomaliesPage.anomalyList().getByRole("button", { name: "Load more" })).toHaveCount(0);
  });

  test("an Agent with nothing flagged says so", async ({ page }) => {
    const { anomaliesPage } = await openTab(page);

    await expect(anomaliesPage.anomalyList()).toContainText("Nothing unusual has been flagged for Sally.");
  });

  test("when checks are off the tab says so and points to settings", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, { normal: mockNormalBehaviour({ detection_enabled: false }) });

    await expect(anomaliesPage.anomalyList()).toContainText("Unusual activity checks are off");
    await expect(anomaliesPage.anomalyList().getByRole("link", { name: "Turn them on in Settings" })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=unusual-activity`,
    );
  });

  test("the learned normal shows usual rates and what the Agent has used", async ({ page }) => {
    const { anomaliesPage } = await openTab(page);

    const normal = anomaliesPage.normal();
    await expect(normal).toContainText("Tool calls per hour");
    await expect(normal).toContainText("usually 100");
    await expect(normal).toContainText("flagged above 152");
    await expect(normal).toContainText("docs.example.com");
    await expect(normal).toContainText("crm read");
    await expect(normal).toContainText("Normal sensitivity");
  });

  test("an Agent without enough history is not checked yet", async ({ page }) => {
    const { anomaliesPage } = await openTab(page, {
      normal: mockNormalBehaviour({ enough_history: false, active_days: 1, rates: [] }),
    });

    await expect(anomaliesPage.normal()).toContainText("Still learning what's normal for Sally");
  });

  test("an Owner raises the sensitivity and caps tokens per hour", async ({ page }) => {
    const { mock, anomaliesPage } = await openTab(page);

    await anomaliesPage.edit(anomaliesPage.normal());
    await anomaliesPage.chooseSensitivity("High");
    await anomaliesPage.normal().getByRole("textbox", { name: "Most tokens per hour" }).fill("200000");
    await anomaliesPage.apply("Save", "Save");

    const put = mock.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({ sensitivity: "HIGH", max_llm_tokens_per_hour: 200000, max_llm_calls_per_hour: null });
    await expect(anomaliesPage.normal()).toContainText("High sensitivity");
  });

  test("a cap too large to keep is refused before saving", async ({ page }) => {
    const { anomaliesPage } = await openTab(page);

    await anomaliesPage.edit(anomaliesPage.normal());
    await anomaliesPage.normal().getByRole("textbox", { name: "Most tokens per hour" }).fill("3000000000");

    await expect(anomaliesPage.normal()).toContainText("Enter a whole number from 1 to 2,147,483,647");
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  });
});

test.describe("Settings · Unusual activity", () => {
  async function openSettings(page: Page, { role = "OWNER", enabled = false } = {}) {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: contextWithRole(role) });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
    const mock = await data.anomalies.interceptDetection({ enabled });
    const anomaliesPage = new AgentAnomaliesPage(page);
    await anomaliesPage.gotoSettings();
    return { mock, anomaliesPage };
  }

  test("checks are off until an Owner turns them on, having been told they may be billed", async ({ page }) => {
    const { mock, anomaliesPage } = await openSettings(page);
    const setting = anomaliesPage.detectionSetting();
    await expect(setting).toContainText("may use an AI model provider");
    await expect(setting).toContainText("billed to that Agent");
    await expect(setting).toContainText("listed on the Agent's Unusual activity tab");

    const toggle = setting.getByRole("switch", { name: "Check Agents for unusual activity" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await toggle.click();

    expect(mock.requests.find((request) => request.method === "PUT")?.body).toEqual({ enabled: true });
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  test("an Owner turns checks off with the same toggle", async ({ page }) => {
    const { mock, anomaliesPage } = await openSettings(page, { enabled: true });
    const toggle = anomaliesPage.detectionSetting().getByRole("switch", { name: "Check Agents for unusual activity" });

    await toggle.click();

    expect(mock.requests.find((request) => request.method === "PUT")?.body).toEqual({ enabled: false });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  test("Members do not see the setting", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: contextWithRole("MEMBER") });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);

    await expect(page.getByRole("complementary").getByRole("link", { name: "Unusual activity" })).toHaveCount(0);
  });
});
