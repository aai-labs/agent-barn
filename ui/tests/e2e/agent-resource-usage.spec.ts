import { expect, test } from "@playwright/test";

import { AgentDetailPage } from "../pages/agent-detail-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { mockResourceUsage } from "../pages/data-support/resource-usage-data-support.po";

/** What the API returns for an agent it has nothing to say about. */
const NOTHING = {
  memory_working_set_bytes: null,
  memory_limit_bytes: null,
  memory_peak_bytes: null,
  cpu_cores: null,
  cpu_limit_cores: null,
  cpu_average_cores: null,
  cpu_throttled_ratio: null,
  series: [],
};

test.describe("Agent Detail Page — Resource usage tab", () => {
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentRequest();
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest();
    await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
  });

  test("sits between Costs and About", async () => {
    await agentDetailPage.gotoResourceUsage();

    await expect(agentDetailPage.resourceUsageTab()).toBeVisible();
    expect((await agentDetailPage.tabLabels()).slice(-3)).toEqual(["Costs", "Resource usage", "About"]);
  });

  test("shows current usage against the container's limits", async ({ page }) => {
    await agentDetailPage.gotoResourceUsage();

    const memory = page.getByTestId("resource-usage-memory-now");
    await expect(memory).toContainText("342 MiB");
    await expect(memory).toContainText("33% of 1 GiB limit");
    await expect(page.getByTestId("resource-usage-memory-peak")).toContainText("668 MiB");
    await expect(page.getByTestId("resource-usage-memory-peak")).toContainText("65% of limit");
    await expect(page.getByTestId("resource-usage-cpu-now")).toContainText("0.05 cores");
    await expect(page.getByTestId("resource-usage-cpu-now")).toContainText("of 0.5 cores");
    await expect(page.getByTestId("resource-usage-cpu-throttled")).toContainText("2%");
  });

  test("draws memory, CPU and throttling over time", async ({ page }) => {
    await agentDetailPage.gotoResourceUsage();

    await expect(page.getByRole("img", { name: "Memory over time" })).toBeVisible();
    await expect(page.getByRole("img", { name: "CPU over time" })).toBeVisible();
    await expect(page.getByRole("img", { name: "CPU throttling over time" })).toBeVisible();
  });

  test("warns when memory is near its limit and the CPU limit is holding the agent back", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID, {
      body: mockResourceUsage({ memory_working_set_bytes: 1_000_000_000, cpu_throttled_ratio: 0.4 }),
    });
    await agentDetailPage.gotoResourceUsage();

    await expect(page.getByTestId("resource-usage-memory-now")).toHaveAttribute("data-tone", "err");
    await expect(page.getByTestId("resource-usage-cpu-throttled")).toHaveAttribute("data-tone", "warn");
    await expect(page.getByTestId("resource-usage-cpu-throttled")).toContainText("40%");
  });

  test("stays calm when usage is well inside its limits", async ({ page }) => {
    await agentDetailPage.gotoResourceUsage();

    await expect(page.getByTestId("resource-usage-memory-now")).toHaveAttribute("data-tone", "ok");
    await expect(page.getByTestId("resource-usage-cpu-throttled")).toHaveAttribute("data-tone", "ok");
  });

  test("asks for the range the reader picks", async ({ page }) => {
    const requests = await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
    await agentDetailPage.gotoResourceUsage();
    await expect(page.getByTestId("resource-usage-memory-now")).toBeVisible();
    expect(requests.map((request) => request.get("range"))).toContain("24h");

    await page.getByTestId("resource-usage-range").click();
    await page.getByRole("option", { name: "Last 7 days" }).click();

    await expect.poll(() => requests.map((request) => request.get("range"))).toContain("7d");
    await expect(page).toHaveURL(/range=7d/);
    await expect(page.getByTestId("resource-usage-memory-peak")).toContainText("last 7 days");
  });

  test("opens on the range in the link", async ({ page }) => {
    const requests = await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
    await agentDetailPage.gotoResourceUsage(MOCK_AGENT_ID, "6h");

    await expect(page.getByTestId("resource-usage-range")).toContainText("Last 6 hours");
    expect(requests.map((request) => request.get("range"))).toEqual(["6h"]);
  });

  test("drops the range from the address when the reader leaves the tab", async ({ page }) => {
    await dataSupportPage.costs.interceptAgentCosts(MOCK_AGENT_ID);
    await agentDetailPage.gotoResourceUsage(MOCK_AGENT_ID, "7d");
    await expect(page).toHaveURL(/range=7d/);

    await agentDetailPage.openCostsTab();

    await expect(page).toHaveURL(/tab=costs/);
    await expect(page).not.toHaveURL(/range=/);
  });

  test.describe("when there is nothing to draw", () => {
    const cases = [
      {
        name: "an agent still on an older helper",
        body: mockResourceUsage({ state: "restart_required", ...NOTHING }),
        text: "Restart this agent to start reporting CPU and memory",
      },
      {
        name: "an environment that cannot report usage",
        body: mockResourceUsage({ state: "unsupported", ...NOTHING }),
        text: "Resource usage isn't available for this agent",
      },
      {
        name: "an agent with no readings yet",
        body: mockResourceUsage({ state: "no_data", ...NOTHING }),
        text: "No usage recorded for this period",
      },
      {
        name: "an environment without monitoring",
        body: mockResourceUsage({ availability: "not_configured", state: null, ...NOTHING }),
        text: "Resource usage isn't set up here",
      },
      {
        name: "a monitoring service that cannot be reached",
        body: mockResourceUsage({ availability: "unavailable", state: null, ...NOTHING }),
        text: "Resource usage is unavailable right now",
      },
    ];

    for (const { name, body, text } of cases) {
      test(`explains ${name} instead of drawing empty charts`, async ({ page }) => {
        await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID, { body });
        await agentDetailPage.gotoResourceUsage();

        await expect(page.getByTestId("resource-usage-notice")).toContainText(text);
        await expect(page.getByTestId("resource-usage-memory-chart")).toHaveCount(0);
        await expect(page.getByTestId("resource-usage-memory-now")).toHaveCount(0);
      });
    }

    test("offers a retry only when the service could not be reached, and recovers", async ({ page }) => {
      await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID, {
        body: mockResourceUsage({ availability: "unavailable", state: null, ...NOTHING }),
      });
      await agentDetailPage.gotoResourceUsage();
      const notice = page.getByTestId("resource-usage-notice");
      await expect(notice).toContainText("unavailable right now");

      await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
      await notice.getByRole("button", { name: "Retry" }).click();

      await expect(page.getByTestId("resource-usage-memory-now")).toContainText("342 MiB");
      await expect(page.getByTestId("resource-usage-notice")).toHaveCount(0);
    });

    test("does not offer a retry for an environment that has no monitoring", async ({ page }) => {
      await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID, {
        body: mockResourceUsage({ availability: "not_configured", state: null, ...NOTHING }),
      });
      await agentDetailPage.gotoResourceUsage();

      await expect(page.getByTestId("resource-usage-notice")).toBeVisible();
      await expect(page.getByTestId("resource-usage-notice").getByRole("button")).toHaveCount(0);
    });
  });

  test("reports a failed request rather than an empty tab, and retries it", async ({ page }) => {
    await dataSupportPage.resourceUsage.interceptAgentResourceUsage(MOCK_AGENT_ID, { status: 500 });
    await agentDetailPage.gotoResourceUsage();

    await expect(page.getByText("We couldn't load resource usage")).toBeVisible();

    await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
    await page.getByRole("button", { name: "Retry" }).click();

    await expect(page.getByTestId("resource-usage-memory-now")).toContainText("342 MiB");
  });

  test.describe("out-of-memory restarts", () => {
    test("says so, and points at the logs", async ({ page }) => {
      await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest({
        body: { termination_reason: "OOMKilled", finished_at: "2026-09-29T11:00:00Z" },
      });
      await agentDetailPage.gotoResourceUsage();

      const callout = page.getByTestId("resource-usage-oom");
      await expect(callout).toContainText("The agent ran out of memory and was restarted");
      await expect(callout).toContainText("1 GiB memory limit");

      await callout.getByRole("button", { name: "See activity and logs" }).click();
      await expect(page).toHaveURL(/tab=activity/);
    });

    test("stays quiet when the last restart had another cause", async ({ page }) => {
      await agentDetailPage.gotoResourceUsage();

      await expect(page.getByTestId("resource-usage-memory-now")).toBeVisible();
      await expect(page.getByTestId("resource-usage-oom")).toHaveCount(0);
    });

    test("does not look for a container on a stopped agent", async ({ page }) => {
      const diagnosticsRequests: string[] = [];
      page.on("request", (request) => {
        if (request.url().includes("/diagnostics")) diagnosticsRequests.push(request.url());
      });
      await dataSupportPage.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
      await agentDetailPage.gotoResourceUsage();

      await expect(page.getByTestId("resource-usage-memory-now")).toBeVisible();
      expect(diagnosticsRequests).toEqual([]);
    });
  });

  test.describe("access", () => {
    const withoutActivityRead = {
      ...mockAgent,
      allowed_actions: mockAgentAllowedActions.filter((action) => action !== "activity.read"),
    };

    test("is hidden from a reader without activity.read", async ({ page }) => {
      await dataSupportPage.agents.interceptGetAgentRequest({ body: withoutActivityRead });
      await agentDetailPage.goto();

      await expect(page.getByRole("button", { name: "About", exact: true })).toBeVisible();
      await expect(agentDetailPage.resourceUsageTab()).toHaveCount(0);
    });

    test("makes no request when the link points at a tab the reader cannot open", async ({ page }) => {
      const requests = await dataSupportPage.resourceUsage.interceptAgentResourceUsage();
      await dataSupportPage.agents.interceptGetAgentRequest({ body: withoutActivityRead });
      await dataSupportPage.costs.interceptAgentCosts(MOCK_AGENT_ID);
      await agentDetailPage.gotoResourceUsage();

      await expect(page.getByRole("button", { name: "Costs", exact: true })).toBeVisible();
      await expect(page.getByTestId("agent-resource-usage-tab")).toHaveCount(0);
      expect(requests).toEqual([]);
    });

    test("is shown to a reader with activity.read but not cost.read", async ({ page }) => {
      await dataSupportPage.agents.interceptGetAgentRequest({
        body: {
          ...mockAgent,
          allowed_actions: mockAgentAllowedActions.filter((action) => action !== "cost.read"),
        },
      });
      await agentDetailPage.gotoResourceUsage();

      await expect(page.getByTestId("resource-usage-memory-now")).toContainText("342 MiB");
    });
  });
});
