import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  PLATFORM_ACME_ID,
  PLATFORM_ADA_ID,
  PLATFORM_CY_ID,
  PLATFORM_GLOBEX_ID,
  PLATFORM_ORPHAN_ID,
  mockCapacity,
  mockPlatformAgent,
  mockPlatformAgentDetails,
  mockPlatformUsage,
  mockPlatformUsageUnavailable,
} from "../pages/data-support/resource-usage-data-support.po";
import { PlatformResourceUsagePage } from "../pages/platform-resource-usage-page.po";

const GIB = 1024 ** 3;

test.describe("Platform resource usage (platform_admin)", () => {
  let usagePage: PlatformResourceUsagePage;
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    usagePage = new PlatformResourceUsagePage(page);
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptListOrganizations({
      items: [
        {
          id: PLATFORM_ACME_ID,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          name: "Acme",
        },
      ],
    });
  });

  test("shows the platform's totals, its organizations and its heaviest agents", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto();

    await expect(usagePage.heading()).toBeVisible();
    // 1 GiB + 1.95 GB + 256 MiB, against three 2 GiB limits.
    await expect(usagePage.stat("memory")).toContainText("3.07 GiB");
    await expect(usagePage.stat("memory")).toContainText("of 6 GiB in limits");
    await expect(usagePage.stat("cpu")).toContainText("0.55 cores");
    // Three containers report, but one has no live agent: the count is of live agents.
    await expect(usagePage.stat("reporting")).toContainText("2");
    await expect(usagePage.stat("reporting")).toContainText("of 2 running or in error");
    await expect(usagePage.stat("near-limit")).toContainText("1");
    await expect(usagePage.stat("throttled")).toContainText("1");

    // Heaviest first, with the container nobody owns last. Three rows is under the top
    // five, so nothing is held back and there is nothing to explain.
    await expect(usagePage.organizationRows()).toHaveCount(3);
    await expect(page.getByTestId("organizations-by-usage-note")).toHaveCount(0);
    await expect(usagePage.organizationRows().nth(0)).toContainText("Globex");
    await expect(usagePage.organizationRows().nth(1)).toContainText("Acme");
    await expect(usagePage.organizationRows().nth(2)).toContainText("No live agent");

    expect(await usagePage.agentIds()).toEqual([PLATFORM_CY_ID, PLATFORM_ADA_ID, PLATFORM_ORPHAN_ID]);
    await expect(usagePage.agentRows().nth(0)).toContainText("Cy");
    await expect(usagePage.agentRows().nth(0)).toContainText("Globex");
    await expect(usagePage.agentRows().nth(0)).toContainText("30%");

    await expect(page.getByTestId("platform-usage-memory-chart")).toBeVisible();
    await expect(page.getByTestId("platform-usage-cpu-chart")).toBeVisible();
  });

  test("lists the top five organizations, keeps the no-live-agent row, and says how many more", async ({
    page,
  }) => {
    // Seven organizations, heaviest first, then the container nobody owns: the order the
    // API sends them in.
    const named = Array.from({ length: 7 }, (_, index) => ({
      organization_id: `00000000-0000-4000-8000-0000000001${String(index).padStart(2, "0")}`,
      organization_name: `Org ${index}`,
      agents_with_container: 1,
      agents_reporting: 1,
      memory_working_set_bytes: (8 - index) * 100_000_000,
      memory_limit_bytes: 2_147_483_648,
      cpu_cores: 0.1,
      cpu_limit_cores: 1,
    }));
    const noLiveAgent = {
      ...named[0],
      organization_id: null,
      organization_name: null,
      agents_with_container: 0,
      memory_working_set_bytes: 50_000_000,
    };
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsage({ organizations: [...named, noLiveAgent] }),
    });

    await usagePage.goto();

    // Five organizations, then the no-live-agent row as a sixth: it is not one of the five.
    await expect(usagePage.organizationRows()).toHaveCount(6);
    await expect(usagePage.organizationRows().nth(0)).toContainText("Org 0");
    await expect(usagePage.organizationRows().nth(4)).toContainText("Org 4");
    await expect(usagePage.organizationRows().nth(5)).toContainText("No live agent");
    await expect(page.getByText("Org 5")).toHaveCount(0);
    await expect(page.getByTestId("organizations-by-usage-note")).toContainText(
      "Showing the top 5 of 7 organizations",
    );
  });

  test("keeps each organization on one compact line, with its reporting count", async () => {
    await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto();

    const rows = usagePage.organizationRows();
    await expect(rows).toHaveCount(3);
    for (const index of [0, 1, 2]) {
      const row = rows.nth(index);
      const box = await row.boundingBox();
      // One line of text plus padding. A wrapped count or a CPU figure pushed onto a
      // second line makes a row twice this tall.
      expect(box?.height ?? Infinity).toBeLessThan(44);
    }
    await expect(rows.nth(0)).toContainText("1 of 1 reporting");

    // Name, count, memory and CPU all sit on the same line.
    const tops = await rows
      .nth(0)
      .locator("span")
      .evaluateAll((spans) =>
        spans.filter((span) => span.textContent?.trim()).map((span) => Math.round(span.getBoundingClientRect().top)),
      );
    expect(new Set(tops).size).toBe(1);
  });

  test("names a container with no live agent by its id, not by a guess", async () => {
    await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto();

    const row = usagePage.agentRows().nth(2);
    await expect(row).toContainText("agent-99999999");
    await expect(row.getByRole("link")).toHaveCount(0);
  });

  test("an organization in the table narrows the page to it", async ({ page }) => {
    const requests = await data.resourceUsage.interceptPlatformResourceUsage({
      body: (params) =>
        params.get("organization_id") === PLATFORM_ACME_ID
          ? mockPlatformUsage({
              organization_id: PLATFORM_ACME_ID,
              totals: {
                agents_with_container: 1,
                agents_reporting: 1,
                memory_working_set_bytes: 1_073_741_824,
                memory_limit_bytes: 2_147_483_648,
                cpu_cores: 0.4,
                cpu_limit_cores: 1,
              },
              agents: [mockPlatformAgent()],
            })
          : mockPlatformUsage(),
    });
    await usagePage.goto();
    await expect(usagePage.organizationRows()).toHaveCount(3);

    await usagePage.organizationRow(PLATFORM_ACME_ID).click();

    await expect(usagePage.agentRows()).toHaveCount(1);
    await expect(usagePage.stat("memory")).toContainText("1 GiB");
    // Narrowed, the card shows that organization alone: not the others, and not the
    // container with no live agent, which the narrowed totals leave out.
    await expect(usagePage.organizationRows()).toHaveCount(1);
    await expect(usagePage.organizationRow(PLATFORM_ACME_ID)).toHaveAttribute("aria-pressed", "true");
    await expect(usagePage.organizationRow(PLATFORM_GLOBEX_ID)).toHaveCount(0);
    await expect(usagePage.organizationRow("none")).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`orgId=${PLATFORM_ACME_ID}`));
    await expect(page).toHaveURL(/orgName=Acme/);
    expect(requests.at(-1)?.get("organization_id")).toBe(PLATFORM_ACME_ID);

    // Clicking it again clears the filter, and the others come back.
    await usagePage.organizationRow(PLATFORM_ACME_ID).click();

    await expect(usagePage.agentRows()).toHaveCount(3);
    await expect(usagePage.organizationRows()).toHaveCount(3);
    await expect(page).not.toHaveURL(/orgId=/);
    expect(requests.at(-1)?.get("organization_id")).toBeNull();
  });

  test("opens already narrowed when the URL carries an organization", async () => {
    const requests = await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto(`?orgId=${PLATFORM_GLOBEX_ID}&orgName=Globex&range=7d`);

    await expect(usagePage.heading()).toBeVisible();
    await expect.poll(() => requests.at(-1)?.get("organization_id")).toBe(PLATFORM_GLOBEX_ID);
    expect(requests.at(-1)?.get("range")).toBe("7d");
  });

  test("the container with no live agent is not a filter", async ({ page }) => {
    const requests = await data.resourceUsage.interceptPlatformResourceUsage();
    await usagePage.goto();
    await expect(usagePage.organizationRows()).toHaveCount(3);
    const before = requests.length;

    const row = usagePage.organizationRow("none");
    await expect(row).toHaveAttribute("aria-disabled", "true");
    // Forced: Playwright will not click an aria-disabled control, but a person can.
    await row.click({ force: true });

    await expect(page).not.toHaveURL(/orgId=/);
    expect(requests.length).toBe(before);
  });

  test("a different time range is asked for from the API", async ({ page }) => {
    const requests = await data.resourceUsage.interceptPlatformResourceUsage();
    await usagePage.goto();
    await expect(usagePage.heading()).toBeVisible();
    expect(requests.at(0)?.get("range")).toBe("24h");

    await usagePage.chooseRange("Last 7 days");

    await expect(page).toHaveURL(/range=7d/);
    await expect.poll(() => requests.at(-1)?.get("range")).toBe("7d");
  });

  test("shows only the ten heaviest agents until asked for the rest", async ({ page }) => {
    const agents = Array.from({ length: 12 }, (_, index) =>
      mockPlatformAgent({
        agent_id: `00000000-0000-4000-8000-0000000000${String(index).padStart(2, "0")}`,
        agent_name: `Agent ${index}`,
        memory_working_set_bytes: 100_000_000 + index * 1_000_000,
      }),
    );
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsage({ agents }),
    });

    await usagePage.goto();

    await expect(usagePage.agentRows()).toHaveCount(10);
    // Heaviest first.
    await expect(usagePage.agentRows().first()).toContainText("Agent 11");

    await page.getByTestId("platform-agents-show-all").click();

    await expect(usagePage.agentRows()).toHaveCount(12);
  });

  test("says so when no agent is reporting", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsage({ agents: [], organizations: [] }),
    });

    await usagePage.goto();

    await expect(page.getByTestId("platform-agents-empty")).toBeVisible();
    // Nobody is waiting on an update, so it does not say they are.
    await expect(page.getByTestId("platform-agents-need-update")).toHaveCount(0);
  });

  test("shows what the pods request beside what the agents use, on each row, in the cards and by organization", async ({
    page,
  }) => {
    const base = mockPlatformUsage();
    const requests: Record<string, { memory: number; cpu: number }> = {
      [PLATFORM_CY_ID]: { memory: 0.5 * GIB, cpu: 0.1 },
    };
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: {
        ...base,
        totals: { ...base.totals, memory_request_bytes: 1.5 * GIB, cpu_request_cores: 0.35 },
        organizations: base.organizations.map((row) =>
          row.organization_name === "Globex" ? { ...row, memory_request_bytes: 0.5 * GIB, cpu_request_cores: 0.1 } : row,
        ),
        agents: base.agents.map((agent) =>
          requests[agent.agent_id]
            ? { ...agent, memory_request_bytes: requests[agent.agent_id].memory, cpu_request_cores: requests[agent.agent_id].cpu }
            : agent,
        ),
      },
    });

    await usagePage.goto();

    // The aggregate cards say how much the agents reporting request and how much they may use.
    const aggregates = page.getByTestId("platform-usage-aggregates");
    await expect(aggregates.getByTestId("platform-usage-memory-requested")).toContainText("1.5 GiB");
    await expect(aggregates.getByTestId("platform-usage-memory-limits")).toContainText("6 GiB");
    await expect(aggregates.getByTestId("platform-usage-cpu-requested")).toContainText("0.35 cores");
    await expect(aggregates.getByTestId("platform-usage-cpu-limits")).toContainText("3 cores");
    // The same agents as the figures above: the two live agents, not the container nobody owns.
    await expect(aggregates.getByTestId("platform-usage-memory-requested")).toContainText(
      "across the 2 agents reporting",
    );
    // Cy asks for 512 MiB of its 2 GiB, so the tick sits a quarter of the way along the bar.
    const cy = usagePage.agentRows().nth(0);
    await expect(cy.getByTestId("platform-agent-memory-request")).toHaveText("requests 512 MiB");
    await expect(cy.getByTestId("platform-agent-cpu-request")).toHaveText("requests 0.1 cores");
    await expect(cy.getByTestId("usage-meter-request-marker")).toHaveCount(2);
    await expect(cy.getByRole("meter").first()).toHaveAttribute("aria-label", /request at 25% of the limit/);
    // An agent whose request was not read says nothing, and has no tick.
    const ada = usagePage.agentRows().nth(1);
    await expect(ada.getByTestId("platform-agent-memory-request")).toHaveCount(0);
    await expect(ada.getByTestId("usage-meter-request-marker")).toHaveCount(0);
    // And the organization rows, on a wide screen.
    const globex = usagePage.organizationRows().nth(0);
    await expect(globex.getByTestId("organization-request-memory")).toHaveText("req 512 MiB");
    await expect(globex.getByTestId("organization-request-cpu")).toHaveText("req 0.1");
    await expect(usagePage.organizationRows().nth(1).getByTestId("organization-request-memory")).toHaveText("—");
    // The extra columns still keep a row on one line.
    const box = await globex.boundingBox();
    expect(box?.height ?? Infinity).toBeLessThan(44);
  });

  test("says nothing about requests when they could not be read", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto();

    await expect(usagePage.stat("memory")).toContainText("of 6 GiB in limits");
    // The limits are known, the requests are not: unknown is a dash, not a zero.
    const aggregates = page.getByTestId("platform-usage-aggregates");
    await expect(aggregates.getByTestId("platform-usage-memory-limits")).toContainText("6 GiB");
    await expect(aggregates.getByTestId("platform-usage-memory-requested")).toContainText("—");
    await expect(aggregates.getByTestId("platform-usage-cpu-requested")).toContainText("—");
    await expect(usagePage.agentRows().nth(0).getByTestId("platform-agent-memory-request")).toHaveCount(0);
    await expect(usagePage.agentRows().nth(0).getByTestId("usage-meter-request-marker")).toHaveCount(0);
  });

  test("says how many agents need an update to report, in the card and on the organization rows", async () => {
    const base = mockPlatformUsage();
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: {
        ...base,
        totals: { ...base.totals, agents_with_container: 4, agents_reporting: 3, agents_restart_required: 2 },
        organizations: base.organizations.map((row) =>
          row.organization_name === "Globex" ? { ...row, agents_with_container: 3, agents_restart_required: 2 } : row,
        ),
      },
    });

    await usagePage.goto();

    await expect(usagePage.stat("reporting")).toContainText("of 4 running or in error · 2 need an update");
    await expect(usagePage.organizationRows().nth(0)).toContainText("1 of 3 reporting · 2 to update");
    // The longer count still fits on one line.
    const box = await usagePage.organizationRows().nth(0).boundingBox();
    expect(box?.height ?? Infinity).toBeLessThan(44);
    // An organization with nothing to update says nothing about it.
    await expect(usagePage.organizationRows().nth(1)).toContainText("1 of 1 reporting");
    await expect(usagePage.organizationRows().nth(1)).not.toContainText("to update");
  });

  test("tells an empty table why: the agents are on an older version", async ({ page }) => {
    const base = mockPlatformUsage();
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: {
        ...base,
        totals: { ...base.totals, agents_reporting: 0, agents_restart_required: 3 },
        agents: [],
        organizations: [],
      },
    });

    await usagePage.goto();

    await expect(page.getByTestId("platform-agents-empty")).toContainText("No agent is reporting CPU or memory right now.");
    await expect(page.getByTestId("platform-agents-need-update")).toContainText(
      "3 agents are running an older version. Their owners can update them from the agent page to start reporting.",
    );
  });

  test("says it in the singular for one agent", async ({ page }) => {
    const base = mockPlatformUsage();
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: { ...base, totals: { ...base.totals, agents_reporting: 0, agents_restart_required: 1 }, agents: [] },
    });

    await usagePage.goto();

    await expect(page.getByTestId("platform-agents-need-update")).toContainText("1 agent is running an older version.");
  });

  test("explains an unreachable source and still shows the database's count", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsageUnavailable(),
    });

    await usagePage.goto();

    await expect(page.getByText("Resource usage is unavailable right now")).toBeVisible();
    await expect(usagePage.stat("memory")).toContainText("—");
    await expect(usagePage.stat("reporting")).toContainText("of 2 running or in error");
    await expect(page.getByTestId("organizations-by-usage")).toHaveCount(0);
    await expect(page.getByTestId("platform-agents-usage")).toHaveCount(0);
  });

  test("explains an environment with no monitoring service", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsageUnavailable("not_configured"),
    });

    await usagePage.goto();

    await expect(page.getByText("Resource usage isn't set up here")).toBeVisible();
  });

  test("shows a failed request as an error with a retry", async ({ page }) => {
    await data.resourceUsage.interceptPlatformResourceUsage({ status: 500 });

    await usagePage.goto();

    await expect(page.getByText("We couldn't load resource usage")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });

  test("marks Resources as the current platform tab", async () => {
    await data.resourceUsage.interceptPlatformResourceUsage();

    await usagePage.goto();

    await expect(usagePage.navLink("Resources")).toHaveAttribute("aria-current", "page");
    await expect(usagePage.navLink("Overview")).not.toHaveAttribute("aria-current", "page");
  });
});

test.describe("Platform resource usage (non platform_admin)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is not accessible to a non platform_admin", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({
      userContext: { ...UserContext, is_platform_admin: false },
    });
    const requests = await data.resourceUsage.interceptPlatformResourceUsage();

    await new PlatformResourceUsagePage(page).goto();

    await expect(page.getByText(/platform admin access required/i)).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 1, name: "Platform Resource Usage" }),
    ).not.toBeVisible();
    // The page never mounted, so nothing asked for cross-organization figures.
    expect(requests).toHaveLength(0);
  });
});



test.describe("Platform namespace quota (platform_admin)", () => {
  let usagePage: PlatformResourceUsagePage;
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    usagePage = new PlatformResourceUsagePage(page);
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptListOrganizations();
  });

  /** The page with the namespace committing this much against these limits. */
  async function openWith(capacity: Record<string, unknown>) {
    const requests = await data.resourceUsage.interceptPlatformResourceUsage({
      body: mockPlatformUsage({ capacity: mockCapacity(capacity) }),
    });
    await usagePage.goto();
    await expect(usagePage.heading()).toBeVisible();
    return requests;
  }

  test("holds what the namespace commits against the quota that was entered", async () => {
    await openWith({
      limits_memory_bytes: 70 * GIB,
      limits_cpu_cores: 24,
      committed_limits_memory_bytes: 46 * GIB,
      committed_limits_cpu_cores: 11.5,
    });

    await expect(usagePage.capacityCard("limits-memory")).toContainText("46 GiB");
    await expect(usagePage.capacityCard("limits-memory")).toContainText("66% of the 70 GiB quota");
    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "ok");
    await expect(usagePage.capacityCard("limits-memory").getByRole("meter")).toHaveAttribute("aria-valuenow", "66");
    await expect(usagePage.capacityCard("limits-cpu")).toContainText("11.5 cores");
    await expect(usagePage.capacityCard("limits-cpu")).toContainText("48% of the 24 cores quota");
    // Well under the limits, so there is nothing to warn about.
    await expect(usagePage.capacityWarning()).toHaveCount(0);
  });

  test("holds the requests beside the limits, because either can stop a new pod", async () => {
    await openWith({
      limits_memory_bytes: 52.5 * GIB,
      limits_cpu_cores: 30,
      requests_memory_bytes: 20 * GIB,
      requests_cpu_cores: 5,
      committed_limits_memory_bytes: 42.5 * GIB,
      committed_limits_cpu_cores: 24.1,
      committed_requests_memory_bytes: 12.25 * GIB,
      committed_requests_cpu_cores: 2.5,
    });

    await expect(usagePage.capacityCard("limits-memory")).toContainText("81% of the 52.5 GiB quota");
    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "warn");
    await expect(usagePage.capacityCard("requests-memory")).toContainText("12.25 GiB");
    await expect(usagePage.capacityCard("requests-memory")).toContainText("61% of the 20 GiB quota");
    await expect(usagePage.capacityCard("requests-memory")).toHaveAttribute("data-state", "ok");
    await expect(usagePage.capacityCard("requests-cpu")).toContainText("50% of the 5 cores quota");
    await expect(usagePage.capacityCard("requests-cpu").getByRole("meter")).toHaveAttribute("aria-valuenow", "50");
  });

  test("warns about the requests alone when they are the line about to run out", async () => {
    await openWith({
      limits_memory_bytes: 52.5 * GIB,
      limits_cpu_cores: 30,
      requests_memory_bytes: 20 * GIB,
      requests_cpu_cores: 5,
      committed_limits_memory_bytes: 10 * GIB,
      committed_limits_cpu_cores: 5,
      committed_requests_memory_bytes: 5 * GIB,
      committed_requests_cpu_cores: 4.8,
    });

    await expect(usagePage.capacityWarning()).toHaveAttribute("data-tone", "err");
    await expect(usagePage.capacityWarning().getByTestId("capacity-warning-requests-cpu")).toContainText(
      "CPU requests committed are 96% of the 5 cores quota (4.8 cores). New agents may fail to start.",
    );
    await expect(usagePage.capacityWarning().getByTestId("capacity-warning-limits-cpu")).toHaveCount(0);
    await expect(usagePage.capacityWarning().getByTestId("capacity-warning-requests-memory")).toHaveCount(0);
  });

  test("the dialog has a box for each quota line and sends all four", async () => {
    await openWith({ limits_memory_bytes: 52.5 * GIB, limits_cpu_cores: 30 });
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();
    await usagePage.openCapacityDialog();

    await expect(usagePage.limitsMemoryInput()).toHaveValue("52.5");
    await expect(usagePage.requestsMemoryInput()).toHaveValue("");
    await usagePage.requestsMemoryInput().fill("20");
    await usagePage.requestsCpuInput().fill("5");
    await usagePage.saveButton().click();

    await expect(usagePage.dialog()).toBeHidden();
    expect(sent).toEqual([
      {
        limits_memory_bytes: 56_371_445_760,
        limits_cpu_cores: 30,
        requests_memory_bytes: 21_474_836_480,
        requests_cpu_cores: 5,
      },
    ]);
  });

  test("warns in amber when the namespace is filling up", async () => {
    await openWith({ limits_memory_bytes: 70 * GIB, committed_limits_memory_bytes: 56 * GIB });

    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "warn");
    await expect(usagePage.capacityWarning()).toHaveAttribute("data-tone", "warn");
    await expect(usagePage.capacityWarning()).toContainText(
      "Memory limits committed are 80% of the 70 GiB quota (56 GiB). Room for new agents is running low.",
    );
  });

  test("warns in red when new agents may fail to start", async () => {
    await openWith({ limits_memory_bytes: 70 * GIB, committed_limits_memory_bytes: 66.5 * GIB });

    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "critical");
    await expect(usagePage.capacityWarning()).toHaveAttribute("data-tone", "err");
    await expect(usagePage.capacityWarning()).toContainText("95% of the 70 GiB quota");
    await expect(usagePage.capacityWarning()).toContainText("New agents may fail to start.");
  });

  test("says the quota is probably out of date when the namespace is past it", async () => {
    await openWith({ limits_memory_bytes: 70 * GIB, committed_limits_memory_bytes: 72 * GIB });

    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "over");
    await expect(usagePage.capacityWarning()).toContainText(
      "Memory limits committed (72 GiB) are above the 70 GiB quota you entered, so what you entered is probably out of date.",
    );
  });

  test("one banner follows the worst of the two, with a line for each that needs it", async () => {
    await openWith({
      limits_memory_bytes: 70 * GIB,
      committed_limits_memory_bytes: 56 * GIB,
      limits_cpu_cores: 24,
      committed_limits_cpu_cores: 23,
    });

    await expect(usagePage.capacityWarning()).toHaveAttribute("data-tone", "err");
    await expect(usagePage.capacityWarning().getByTestId("capacity-warning-limits-memory")).toBeVisible();
    await expect(usagePage.capacityWarning().getByTestId("capacity-warning-limits-cpu")).toBeVisible();
  });

  test("a quota line that was never entered asks for one instead of guessing", async ({ page }) => {
    await openWith({});

    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "unset");
    await expect(usagePage.capacityCard("limits-memory")).toContainText("No quota entered");
    // The committed figure is still shown, since it needs no limit to be read.
    await expect(usagePage.capacityCard("limits-memory")).toContainText("4 GiB");
    await expect(usagePage.capacityWarning()).toHaveCount(0);

    await usagePage.capacityCard("limits-memory").getByRole("button", { name: "Enter quota" }).click();

    await expect(usagePage.dialog()).toBeVisible();
    await expect(usagePage.limitsMemoryInput()).toHaveValue("");
    await expect(page.getByText("Last changed")).toHaveCount(0);
  });

  test("keeps the ceilings, and says the committed figure is missing, when the source is down", async () => {
    await data.resourceUsage.interceptPlatformResourceUsage({
      body: {
        ...mockPlatformUsageUnavailable(),
        capacity: mockCapacity({
          limits_memory_bytes: 70 * GIB,
          committed_limits_memory_bytes: null,
          committed_limits_cpu_cores: null,
        }),
      },
    });
    await usagePage.goto();

    await expect(usagePage.capacityCard("limits-memory")).toHaveAttribute("data-state", "unknown");
    await expect(usagePage.capacityCard("limits-memory")).toContainText("Committed figure not available");
    await expect(usagePage.capacityCard("limits-memory")).toContainText("70 GiB");
    // Editable even now: the limits are in the database, not in Prometheus.
    await usagePage.openCapacityDialog();
    await expect(usagePage.limitsMemoryInput()).toHaveValue("70");
  });

  test("the dialog opens on what is saved, in GiB and cores, with when it last changed", async ({ page }) => {
    await openWith({
      limits_memory_bytes: 70 * GIB,
      limits_cpu_cores: 24,
      ceilings_updated_at: "2026-09-30T08:30:00Z",
    });

    await usagePage.openCapacityDialog();

    await expect(usagePage.dialog()).toBeVisible();
    await expect(usagePage.limitsMemoryInput()).toHaveValue("70");
    await expect(usagePage.limitsCpuInput()).toHaveValue("24");
    await expect(page.getByText("Last changed")).toBeVisible();
    await expect(usagePage.dialog()).toContainText("limits.memory");
  });

  test("saving sends whole bytes and refreshes the page", async ({ page }) => {
    const requests = await openWith({ limits_memory_bytes: 70 * GIB, limits_cpu_cores: 24 });
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();
    await usagePage.openCapacityDialog();
    const before = requests.length;

    await usagePage.limitsMemoryInput().fill("62.5");
    await usagePage.limitsCpuInput().fill("16");
    await usagePage.saveButton().click();

    await expect(usagePage.dialog()).toBeHidden();
    // 62.5 GiB, as a whole number of bytes.
    expect(sent).toEqual([
      { limits_memory_bytes: 67_108_864_000, limits_cpu_cores: 16, requests_memory_bytes: null, requests_cpu_cores: null },
    ]);
    await expect.poll(() => requests.length).toBeGreaterThan(before);
    await expect(page.getByText("Namespace quota saved")).toBeVisible();
  });

  test("a blank field clears that limit", async () => {
    await openWith({ limits_memory_bytes: 70 * GIB, limits_cpu_cores: 24 });
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();
    await usagePage.openCapacityDialog();

    await usagePage.limitsMemoryInput().fill("");
    await usagePage.limitsCpuInput().fill("");
    await usagePage.saveButton().click();

    await expect(usagePage.dialog()).toBeHidden();
    expect(sent).toEqual([
      { limits_memory_bytes: null, limits_cpu_cores: null, requests_memory_bytes: null, requests_cpu_cores: null },
    ]);
  });

  test("text that is not a positive number is caught before anything is sent", async ({ page }) => {
    await openWith({});
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();
    await usagePage.openCapacityDialog();

    await usagePage.limitsMemoryInput().fill("lots");
    await usagePage.limitsCpuInput().fill("0");
    await usagePage.saveButton().click();

    await expect(page.getByText("Enter a number above 0, or leave it blank.")).toHaveCount(2);
    await expect(usagePage.dialog()).toBeVisible();
    expect(sent).toHaveLength(0);
  });

  test("an error from the API stays in the dialog, next to what caused it", async () => {
    await openWith({});
    await data.resourceUsage.interceptUpdateResourceLimits({
      status: 422,
      detail: "limits_memory_bytes must be at most 1125899906842624",
    });
    await usagePage.openCapacityDialog();

    await usagePage.limitsMemoryInput().fill("70");
    await usagePage.saveButton().click();

    await expect(usagePage.dialog().getByTestId("capacity-limits-error")).toBeVisible();
    await expect(usagePage.dialog()).toBeVisible();
  });

  test("cancelling throws the edit away, so the next opening starts from what is saved", async () => {
    await openWith({ limits_memory_bytes: 70 * GIB });
    await usagePage.openCapacityDialog();
    await usagePage.limitsMemoryInput().fill("5");

    await usagePage.dialog().getByRole("button", { name: "Cancel" }).click();
    await expect(usagePage.dialog()).toBeHidden();
    await usagePage.openCapacityDialog();

    await expect(usagePage.limitsMemoryInput()).toHaveValue("70");
  });
});

test.describe("Platform opened agent rows (platform_admin)", () => {
  let usagePage: PlatformResourceUsagePage;
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    usagePage = new PlatformResourceUsagePage(page);
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptListOrganizations();
    await data.resourceUsage.interceptPlatformResourceUsage();
  });

  test("rows start closed, and a closed row asks for nothing", async ({ page }) => {
    const asked = await data.resourceUsage.interceptPlatformAgentDetails();

    await usagePage.goto();

    await expect(usagePage.agentRows()).toHaveCount(3);
    await expect(usagePage.agentDetails()).toHaveCount(0);
    await expect(page.getByTestId("platform-agent-details-row")).toHaveCount(0);
    expect(asked).toHaveLength(0);
  });

  test("opening a row shows the same Status and Resource usage panels as the organization page", async () => {
    const asked = await data.resourceUsage.interceptPlatformAgentDetails();
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    await expect(usagePage.agentDetails()).toBeVisible();
    expect(asked).toEqual([PLATFORM_CY_ID]);

    const status = usagePage.agentDetails().getByTestId("platform-agent-status");
    await expect(status).toContainText("Working");
    await expect(status).toContainText("hermes");
    await expect(status).toContainText("Restarts");
    await expect(status).toContainText("3");
    await expect(status).toContainText("Last stopped by");
    await expect(status).toContainText("OOMKilled");

    const usage = usagePage.agentDetails().getByTestId("platform-agent-usage");
    await expect(usage).toContainText("1.82 GiB of 2 GiB");
    await expect(usage).toContainText("0.1 of 1 cores");
    await expect(usage).toContainText("Peak memory, 24h");
    await expect(usage).toContainText("30%");
    await expect(usage.getByRole("img", { name: "Memory over time" })).toBeVisible();
  });

  test("has no Cost panel and no links, since an organization's agent pages are not an admin's to open", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails();
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    await expect(usagePage.agentDetails()).toBeVisible();
    await expect(usagePage.agentDetails().getByRole("heading", { name: "Cost" })).toHaveCount(0);
    await expect(usagePage.agentDetails().getByRole("heading", { name: "Status" })).toBeVisible();
    await expect(usagePage.agentDetails().getByRole("heading", { name: "Resource usage" })).toBeVisible();
    await expect(usagePage.agentDetails().getByRole("link")).toHaveCount(0);
  });

  test("clicking the row opens it, and clicking it again closes it", async ({ page }) => {
    await data.resourceUsage.interceptPlatformAgentDetails();
    await usagePage.goto();
    const row = page.locator(`[data-testid="platform-agent-usage-row"][data-agent-id="${PLATFORM_ADA_ID}"]`);

    await row.getByText("Ada").click();
    await expect(usagePage.agentToggle(PLATFORM_ADA_ID)).toHaveAttribute("aria-expanded", "true");
    await expect(usagePage.agentDetails()).toBeVisible();

    await row.getByText("Ada").click();
    await expect(usagePage.agentToggle(PLATFORM_ADA_ID)).toHaveAttribute("aria-expanded", "false");
    await expect(usagePage.agentDetails()).toHaveCount(0);
  });

  test("more than one row can be open, each showing its own agent", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails({
      body: (agentId) =>
        mockPlatformAgentDetails({
          agent_id: agentId,
          name: agentId === PLATFORM_CY_ID ? "Cy" : "Ada",
          restart_count: agentId === PLATFORM_CY_ID ? 3 : 0,
        }),
    });
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();
    await usagePage.agentToggle(PLATFORM_ADA_ID).click();

    await expect(usagePage.agentDetails()).toHaveCount(2);
  });

  test("a row stays open when the table is sorted", async ({ page }) => {
    await data.resourceUsage.interceptPlatformAgentDetails();
    await usagePage.goto();
    await usagePage.agentToggle(PLATFORM_CY_ID).click();
    await expect(usagePage.agentDetails()).toBeVisible();

    await page.getByTestId("platform-agents-sort-cpu").click();

    await expect(usagePage.agentToggle(PLATFORM_CY_ID)).toHaveAttribute("aria-expanded", "true");
    await expect(usagePage.agentDetails()).toBeVisible();
  });

  test("an agent in error shows its failure summary and that it needs attention", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails({
      body: (agentId) =>
        mockPlatformAgentDetails({
          agent_id: agentId,
          status: "ERROR",
          health_status: "error",
          last_error_summary: "Couldn't start — the namespace is out of quota",
          restart_count: null,
          termination_reason: null,
          resource_usage: {
            ...mockPlatformAgentDetails().resource_usage,
            state: "no_data",
            memory_working_set_bytes: null,
            series: [],
          },
        }),
    });
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    const status = usagePage.agentDetails().getByTestId("platform-agent-status");
    await expect(status).toContainText("Needs attention");
    await expect(status).toContainText("Couldn't start — the namespace is out of quota");
    await expect(status).not.toContainText("Restarts");
    await expect(usagePage.agentDetails().getByTestId("platform-agent-usage")).toContainText(
      "No usage recorded for this period",
    );
  });

  test("a stopped agent says it is idle and that usage is recorded while it runs", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails({
      body: (agentId) =>
        mockPlatformAgentDetails({
          agent_id: agentId,
          status: "STOPPED",
          health_status: null,
          restart_count: null,
          termination_reason: null,
          resource_usage: null,
        }),
    });
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    await expect(usagePage.agentDetails().getByTestId("platform-agent-status")).toContainText("Idle");
    await expect(usagePage.agentDetails().getByTestId("platform-agent-usage")).toContainText(
      "Stopped. Usage is recorded while the agent runs.",
    );
  });

  test("a container with no live agent has nothing to open", async ({ page }) => {
    const asked = await data.resourceUsage.interceptPlatformAgentDetails();
    await usagePage.goto();
    const orphan = page.locator(
      `[data-testid="platform-agent-usage-row"][data-agent-id="${PLATFORM_ORPHAN_ID}"]`,
    );

    await expect(orphan.getByRole("button")).toHaveCount(0);
    await orphan.getByText("agent-99999999").click();

    await expect(usagePage.agentDetails()).toHaveCount(0);
    expect(asked).toHaveLength(0);
  });

  test("a failed request is said inline, in both panels, and the row stays", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails({ status: 500 });
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    await expect(usagePage.agentDetails().getByTestId("platform-agent-status")).toContainText(
      "Status couldn't be loaded.",
    );
    await expect(usagePage.agentDetails().getByTestId("platform-agent-usage")).toContainText(
      "Resource usage couldn't be loaded.",
    );
    await expect(usagePage.agentRows()).toHaveCount(3);
  });

  test("an unexpected health word from the runtime does not blank the panel", async () => {
    await data.resourceUsage.interceptPlatformAgentDetails({
      body: (agentId) => mockPlatformAgentDetails({ agent_id: agentId, health_status: "wedged" }),
    });
    await usagePage.goto();

    await usagePage.agentToggle(PLATFORM_CY_ID).click();

    // Read as an error, which the status line draws as Disconnected, and the rest still shows.
    await expect(usagePage.agentDetails().getByTestId("platform-agent-status")).toContainText("Disconnected");
    await expect(usagePage.agentDetails().getByTestId("platform-agent-usage")).toContainText("1.82 GiB of 2 GiB");
  });
});
