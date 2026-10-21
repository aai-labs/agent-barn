import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ENV_ACME_ID,
  ENV_ORPHAN_ID,
  mockEnvironmentHealth,
} from "../pages/data-support/environment-health-data-support.po";
import { EnvironmentHealthPage } from "../pages/environment-health-page.po";

const GIB = 1024 ** 3;

test.describe("Platform environment health (platform_admin)", () => {
  let healthPage: EnvironmentHealthPage;
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    healthPage = new EnvironmentHealthPage(page);
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
  });

  test("shows a full storage quota as the reason agents fail to start", async () => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await healthPage.goto();

    await expect(healthPage.heading()).toBeVisible();
    await expect(healthPage.level()).toHaveAttribute("data-level", "critical");
    await expect(healthPage.capacityLine("requests.storage")).toHaveAttribute("data-level", "critical");
    await expect(healthPage.capacityLine("requests.storage")).toContainText("30 GiB");
    await expect(healthPage.capacityWarning()).toContainText("New agents can't get a volume");
    await expect(healthPage.capacityLine("pods")).toContainText("No quota entered");

    const [failed] = await healthPage.failedAgents().all();
    await expect(failed).toContainText("Cy");
    await expect(failed).toContainText("requests.storage: requested 1Gi, used 30Gi, limit 30Gi");
  });

  test("names agents with their organization and links only to Platform pages", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await healthPage.goto();

    const issue = healthPage.podIssues().first();
    await expect(issue).toContainText("CrashLoopBackOff · restarted 6 times · last stopped: OOMKilled");
    await expect(issue).toContainText("Ada");
    await expect(issue.getByRole("link", { name: "Acme" })).toHaveAttribute(
      "href",
      `/dashboard/platform/organizations/${ENV_ACME_ID}`,
    );
    await expect(healthPage.unhealthyRuntimes()).toContainText("never connected");
    await expect(healthPage.unhealthyRuntimes()).toContainText("The pod itself looks ready");
    // No link anywhere on the page leads into an Organization's own agent pages.
    await expect(page.locator('a[href*="/agents/"]')).toHaveCount(0);
  });

  test("breaks storage down by owner and lists the orphaned claim", async () => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await healthPage.goto();

    await expect(healthPage.volumeGroup("infrastructure")).toContainText("10 GiB");
    await expect(healthPage.volumeGroup("orphaned")).toContainText("1 claim");
    await expect(healthPage.volumeGroup("stopped_agents")).toHaveCount(0);
    await expect(healthPage.volumeAttention()).toContainText(`agent-${ENV_ORPHAN_ID}`);
    await expect(healthPage.volumeAttention()).toContainText("Orphaned");
  });

  test("says which parts the service account may not read instead of showing them empty", async () => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await healthPage.goto();

    await expect(healthPage.sourcesNotice()).toContainText("Resource quota not permitted for the service account");
    await expect(healthPage.section("events")).toContainText("not permitted for the service account");
    await expect(healthPage.section("capacity")).toContainText("can't read the namespace's ResourceQuota");
  });

  test("a readable quota is shown as the cluster's own figures", async () => {
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        level: "ok",
        sources: [{ source: "resource_quotas", state: "available" }, { source: "pods", state: "available" }],
        capacity: [
          {
            resource: "requests.storage",
            unit: "bytes",
            source: "quota",
            used: 12 * GIB,
            hard: 30 * GIB,
            ratio: 0.4,
            level: "ok",
          },
        ],
        failed_agents: [],
        unhealthy_runtimes: [],
        workloads: { pods_total: 3, pods_ready: 3, issues: [] },
        alerts: [],
      }),
    });

    await healthPage.goto();

    await expect(healthPage.level()).toHaveAttribute("data-level", "ok");
    await expect(healthPage.section("capacity")).toContainText("Read from the namespace's ResourceQuota");
    await expect(healthPage.capacityLine("requests.storage")).toContainText("40% of 30 GiB");
    await expect(healthPage.capacityWarning()).toHaveCount(0);
    await expect(healthPage.section("workloads")).toContainText("Every pod is running normally");
  });

  test("the quota dialog offers every line and sends only what it shows", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth();
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();

    await healthPage.goto();
    await healthPage.openQuotaDialog();

    await expect(healthPage.quotaInput("requests.storage (GiB)")).toHaveValue("30");
    await expect(healthPage.quotaInput("pods")).toHaveValue("");
    await expect(healthPage.quotaInput("limits.memory (GiB)")).toHaveValue("52");

    await healthPage.quotaInput("pods").fill("2.5");
    await healthPage.saveButton().click();
    await expect(healthPage.dialog()).toContainText("Enter a whole number above 0");
    expect(sent).toEqual([]);

    await healthPage.quotaInput("pods").fill("60");
    await healthPage.quotaInput("requests.storage (GiB)").fill("50");
    await healthPage.saveButton().click();

    await expect(healthPage.dialog()).toBeHidden();
    expect(sent).toEqual([
      {
        requests_storage_bytes: 50 * GIB,
        pods: 60,
        limits_memory_bytes: 52 * GIB,
        limits_cpu_cores: 30,
        requests_memory_bytes: 20 * GIB,
        requests_cpu_cores: 5,
      },
    ]);
    await expect(page.getByText("Namespace quota saved")).toBeVisible();
  });

  test("is where the System area opens, listed first in its panel", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await page.goto("/dashboard/platform/event-deliveries");
    const system = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "System", exact: true });
    await expect(system).toHaveAttribute("href", "/dashboard/platform/environment-health");
    await expect(
      page.getByRole("complementary").getByRole("link").first(),
    ).toHaveText("Environment health");

    await healthPage.goto();
    await expect(healthPage.heading()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("System/Environment health");
  });

  test("a failed load can be retried", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth({ status: 500 });

    await healthPage.goto();

    await expect(page.getByText("We couldn't load environment health")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("fits the screen without scrolling sideways", async ({ page }) => {
      await data.environmentHealth.interceptEnvironmentHealth();

      await healthPage.goto();
      await expect(healthPage.capacityLine("requests.storage")).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBe(0);
    });
  });
});
