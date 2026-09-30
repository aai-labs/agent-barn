import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentActivitySummary,
  mockAgentAllowedActions,
  mockAgentWake,
  mockUserAgentWake,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

test.describe("Agent Detail Page — Activity tab", () => {
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
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await dataSupportPage.agents.interceptGetAgentActivityRequest();
    await dataSupportPage.agents.interceptGetAgentWakesRequest();
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest();
  });

  async function openActivity(page: import("@playwright/test").Page) {
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await page.getByRole("button", { name: "Activity", exact: true }).click();
  }

  test("shows crash evidence separately from historical spend", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentActivityRequest({ body: {
      ...mockAgentActivitySummary, last_call_at: "2026-09-17T11:29:00Z",
    } });
    await openActivity(page);
    const diagnostics = agentDetailPage.runtimeDiagnostics();
    await expect(diagnostics).toContainText("CrashLoopBackOff");
    await expect(diagnostics).toContainText("21");
    await expect(diagnostics).toContainText("Error (exit 1)");
    await expect(diagnostics).toContainText("Legacy workspace setup state requires migration");
    await expect(diagnostics).toContainText("2026-09-17 11:29:00 UTC");
    await expect(diagnostics).toContainText("not the start of a crash loop");
  });

  test("keeps usage readable when diagnostics fail and supports retry", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest({ status: 503 });
    await openActivity(page);
    const diagnostics = agentDetailPage.runtimeDiagnostics();
    await expect(diagnostics).toContainText("Runtime diagnostics unavailable");
    await expect(page.getByTestId("agent-activity-summary")).toContainText("$51.55");
    await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest();
    await diagnostics.getByRole("button", { name: "Retry diagnostics" }).click();
    await expect(diagnostics).toContainText("CrashLoopBackOff");
  });

  test("keeps runtime evidence available when usage fails", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentActivityRequest({ status: 503 });
    await openActivity(page);
    await expect(agentDetailPage.runtimeDiagnostics()).toContainText("CrashLoopBackOff");
    await expect(agentDetailPage.runtimeDiagnostics()).toContainText("Usage unavailable");
  });

  test("distinguishes unavailable previous logs from an empty log", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentDiagnosticsRequest({ body: {
      previous_logs: [], previous_logs_available: false,
    } });
    await openActivity(page);
    await expect(agentDetailPage.runtimeDiagnostics()).toContainText("Logs unavailable for this container instance");
    await expect(agentDetailPage.runtimeDiagnostics()).toContainText("Starting gateway");
  });

  test("summarises what the agent spent and how often it woke", async ({ page }) => {
    await openActivity(page);

    const summary = page.getByTestId("agent-activity-summary");
    await expect(summary).toContainText("$51.55");
    await expect(summary).toContainText("32");
    // The cadence is the fingerprint of a schedule rather than demand.
    await expect(summary).toContainText("about every 30 minutes");
  });

  test("says plainly when nobody asked for the work", async ({ page }) => {
    await openActivity(page);

    const callout = page.getByTestId("agent-activity-background-callout");
    await expect(callout).toBeVisible();
    await expect(callout).toContainText("No nearby messages recorded for Maya");
    await expect(callout).toContainText("$51.55");
    await expect(callout).toContainText("about every 30 minutes");
  });

  test("keeps quiet when the work was asked for", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentActivityRequest({
      body: {
        ...mockAgentActivitySummary,
        by_trigger: [
          { trigger: "user", wakes: 6, calls: 28, spend: 48.0, prompt_tokens: 3_000_000 },
          { trigger: "background", wakes: 1, calls: 4, spend: 3.55, prompt_tokens: 700_000 },
        ],
      },
    });
    await openActivity(page);

    await expect(page.getByTestId("agent-activity-summary")).toContainText("$51.55");
    await expect(page.getByTestId("agent-activity-background-callout")).toBeHidden();
  });

  test("reports the prompt size spread behind the spend", async ({ page }) => {
    await openActivity(page);

    const spread = page.getByTestId("agent-activity-prompt-size");
    await expect(spread).toContainText("77.0k");
    await expect(spread).toContainText("81.6k");
    await expect(spread).toContainText("121.4k");
    await expect(spread).toContainText("128.9k");
  });

  test("lists each period with its calls, tokens and spend", async ({ page }) => {
    await openActivity(page);

    const byPeriod = page.getByTestId("agent-activity-by-period");
    await expect(byPeriod).toContainText("Sep 10");
    await expect(byPeriod).toContainText("Sep 12");
    await expect(byPeriod).toContainText("2.3M");
    await expect(byPeriod).toContainText("$31.45");
    // A bucket with nothing in it is not a row worth reading.
    await expect(byPeriod).not.toContainText("Sep 11");
  });

  test("lists each wake and what started it", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentWakesRequest({
      items: [mockAgentWake, mockUserAgentWake],
    });
    await openActivity(page);

    const wakes = page.getByTestId("agent-activity-wakes").locator("tbody");
    await expect(wakes).toContainText("No nearby message");
    await expect(wakes).toContainText("Nearby message");
    // Prompt size per call is a range when the calls in a burst differed.
    await expect(wakes).toContainText("116.9k–117.1k");
  });

  test("pressing a period's call count narrows the calls to that period", async ({
    page,
  }) => {
    const requested: URLSearchParams[] = [];
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest({
      onRequest: (url) => requested.push(url.searchParams),
    });
    await openActivity(page);
    await expect(page.getByTestId("agent-activity-by-period")).toContainText("Sep 12");

    await page
      .getByTestId("agent-activity-by-period")
      .getByRole("button", { name: /^Show the 20 calls from .*Sep 12/ })
      .click();

    await expect(page.getByTestId("agent-activity-calls")).toContainText("Narrowed to");
    await expect
      .poll(() => requested.at(-1)?.get("from_date"))
      .toBe("2026-09-12T00:00:00.000Z");
    expect(requested.at(-1)?.get("to_date")).toBe("2026-09-13T00:00:00.000Z");
  });

  test("pressing a wake's call count narrows the calls to that burst", async ({
    page,
  }) => {
    const requested: URLSearchParams[] = [];
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest({
      onRequest: (url) => requested.push(url.searchParams),
    });
    await openActivity(page);

    await page
      .getByTestId("agent-activity-wakes")
      .getByRole("button", { name: /^Show the 4 calls in the wake at / })
      .click();

    await expect
      .poll(() => requested.at(-1)?.get("from_date"))
      .toBe("2026-09-12T11:29:00.000Z");
    // The window is half-open, so the burst's last call needs room inside it.
    expect(requested.at(-1)?.get("to_date")).toBe("2026-09-12T11:29:43.000Z");
  });

  test("cuts a partial first or last period to the summary's window", async ({ page }) => {
    // The default window runs from a moment 30 days ago to now, so it usually
    // starts and ends partway through a bucket.
    await dataSupportPage.agents.interceptGetAgentActivityRequest({
      body: {
        ...mockAgentActivitySummary,
        from_date: "2026-09-10T06:00:00Z",
        to_date: "2026-09-12T18:00:00Z",
      },
    });
    const requested: URLSearchParams[] = [];
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest({
      onRequest: (url) => requested.push(url.searchParams),
    });
    await openActivity(page);
    const byPeriod = page.getByTestId("agent-activity-by-period");

    await byPeriod.getByRole("button", { name: /^Show the 12 calls from .*Sep 10/ }).click();
    await expect
      .poll(() => requested.at(-1)?.get("from_date"))
      .toBe("2026-09-10T06:00:00.000Z");
    expect(requested.at(-1)?.get("to_date")).toBe("2026-09-11T00:00:00.000Z");

    await byPeriod.getByRole("button", { name: /^Show the 20 calls from .*Sep 12/ }).click();
    await expect
      .poll(() => requested.at(-1)?.get("from_date"))
      .toBe("2026-09-12T00:00:00.000Z");
    expect(requested.at(-1)?.get("to_date")).toBe("2026-09-12T18:00:00.000Z");
  });

  test("can narrow to the work nobody asked for", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentWakesRequest({
      items: [mockAgentWake, mockUserAgentWake],
    });
    const requested: URLSearchParams[] = [];
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest({
      onRequest: (url) => requested.push(url.searchParams),
    });
    await openActivity(page);
    await expect(page.getByTestId("agent-activity-wakes").locator("tbody")).toContainText(
      "Nearby message",
    );

    await page.getByTestId("agent-activity-background-callout")
      .getByRole("button", { name: "Show only this work" })
      .click();

    // Scoped to the rows: the filter control itself is labelled "Nearby message".
    const rows = page.getByTestId("agent-activity-wakes").locator("tbody");
    await expect(rows).not.toContainText("Nearby message");
    await expect.poll(() => requested.at(-1)?.get("trigger")).toBe("background");
  });

  test("lists the individual calls behind the rows", async ({ page }) => {
    await openActivity(page);

    const calls = page.getByTestId("agent-activity-calls");
    await expect(calls).toContainText("glm-5.3");
    await expect(calls).toContainText("117.0k");
    await expect(calls).toContainText("4.1s");
  });

  test("clearing the date range also clears the old drill-down", async ({ page }) => {
    await agentDetailPage.openFocusedActivity(MOCK_AGENT_ID);
    await expect(page.getByTestId("agent-activity-calls")).toContainText("Narrowed to");
    await agentDetailPage.clearActivityDates();
    await expect(page.getByTestId("agent-activity-calls")).not.toContainText("Narrowed to");
    await expect(page).not.toHaveURL(/focusFrom=/);
  });

  test("survives a refresh with the drill-down intact", async ({ page }) => {
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=activity` +
        "&focusFrom=2026-09-12T11%3A29%3A00.000Z&focusTo=2026-09-12T11%3A29%3A43.000Z",
    );

    await expect(page.getByTestId("agent-activity-calls")).toContainText("Narrowed to");
  });

  test("says so when the reader has no access to this agent's activity", async ({
    page,
  }) => {
    await dataSupportPage.agents.interceptGetAgentActivityRequest({ status: 403 });
    await openActivity(page);

    await expect(
      page.getByText("You don't have access to this agent's activity."),
    ).toBeVisible();
  });

  test("gives a reader who cannot see spend the runtime evidence alone", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: mockAgentAllowedActions.filter((action) => action !== "cost.read"),
      },
    });
    const usageReads: string[] = [];
    page.on("request", (request) => {
      if (/\/agents\/[^/]+\/activity(\/|\?|$)/.test(new URL(request.url()).pathname)) {
        usageReads.push(request.url());
      }
    });
    await openActivity(page);

    await expect(agentDetailPage.runtimeDiagnostics()).toContainText("CrashLoopBackOff");
    await expect(page.getByTestId("agent-activity-usage-restricted")).toBeVisible();
    await expect(page.getByTestId("agent-activity-summary")).toBeHidden();
    // No usage read is made, so there is nothing to 403.
    expect(usageReads).toEqual([]);
  });

  test("hides the tab from a reader without activity access", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: mockAgentAllowedActions.filter((action) => action !== "activity.read"),
      },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByRole("button", { name: "About", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Activity", exact: true })).toBeHidden();
  });

  test("offers a retry when wakes fail to load", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentWakesRequest({ status: 503 });
    await openActivity(page);
    const wakes = page.getByTestId("agent-activity-wakes");
    await expect(wakes).toContainText("We couldn't load this agent's wakes");

    await dataSupportPage.agents.interceptGetAgentWakesRequest();
    await wakes.getByRole("button", { name: "Retry wakes" }).click();

    await expect(
      wakes.getByRole("button", { name: /^Show the 4 calls in the wake at / }),
    ).toBeVisible();
  });

  test("offers a retry when calls fail to load", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest({ status: 503 });
    await openActivity(page);
    const calls = page.getByTestId("agent-activity-calls");
    await expect(calls).toContainText("We couldn't load this agent's calls");

    await dataSupportPage.agents.interceptGetAgentActivityCallsRequest();
    await calls.getByRole("button", { name: "Retry calls" }).click();

    await expect(calls.getByRole("table")).toBeVisible();
  });
});
