import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  PLATFORM_ACME_ID,
  PLATFORM_ADA_ID,
  PLATFORM_CY_ID,
  PLATFORM_GLOBEX_ID,
  PLATFORM_ORPHAN_ID,
  mockPlatformAgent,
  mockPlatformUsage,
  mockPlatformUsageUnavailable,
} from "../pages/data-support/resource-usage-data-support.po";
import { PlatformResourceUsagePage } from "../pages/platform-resource-usage-page.po";

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
