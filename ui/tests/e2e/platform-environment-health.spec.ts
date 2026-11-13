import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ENV_ACME_ID,
  ENV_ADA_ID,
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
    await expect(healthPage.capacityLine("persistentvolumeclaims")).toHaveAttribute("data-level", "critical");
    await expect(healthPage.capacityLine("persistentvolumeclaims")).toContainText("100% of 60");
    await expect(healthPage.capacityLine("services")).toContainText("No quota entered");

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

  test("a service OOM-killed through the week is listed with its restarts in the window", async () => {
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        workloads: {
          pods_total: 10,
          pods_ready: 10,
          issues: [
            {
              pod_name: "rabbitmq-0",
              workload_name: "rabbitmq",
              kind: "infrastructure",
              agent: null,
              phase: "Running",
              ready: true,
              restart_count: 15,
              restarts_in_window: 15,
              repeatedly_restarting: true,
              oom_killed: true,
              termination_reason: "OOMKilled",
              last_restart_at: "2026-10-18T12:00:00Z",
              created_at: "2026-10-01T12:00:00Z",
            },
          ],
        },
      }),
    });

    await healthPage.goto();

    await expect(healthPage.podIssues().first()).toContainText(
      "Running · restarted 15 times in the last 7 days · ran out of memory",
    );
    await expect(healthPage.podIssues().first()).not.toContainText("last stopped: OOMKilled");
    await expect(healthPage.section("workloads")).toContainText("ran out of memory in the last 7 days");
  });

  test("shows the deployed build, how long ago it rolled out, and services left behind", async ({ page }) => {
    const sixDaysAgo = new Date(Date.now() - 6 * 86_400_000 - 60_000).toISOString();
    const sha = "7f306e1b4c2d9a8e5f60718293a4b5c6d7e8f901";
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        deployed: { build_sha: sha, rolled_out_at: sixDaysAgo, mixed: true, behind: ["agentbarn-gateway"] },
        services: [
          {
            name: "agentbarn-gateway",
            kind: "Deployment",
            desired_replicas: 1,
            ready_replicas: 1,
            level: "warning",
            build_sha: "0123456789abcdef",
            rollout: "stuck",
            rolled_out_at: null,
          },
          {
            name: "agentbarn-api",
            kind: "Deployment",
            desired_replicas: 1,
            ready_replicas: 1,
            level: "ok",
            build_sha: sha,
            rollout: "complete",
            rolled_out_at: sixDaysAgo,
          },
        ],
      }),
    });

    await healthPage.goto();

    const deployed = page.getByTestId("environment-deployed");
    await expect(deployed).toContainText("Build 7f306e1");
    await expect(deployed).toContainText("rolled out 6 days ago");
    await expect(deployed).toContainText("agentbarn-gateway is on another build");
    await expect(page.getByTestId("service-agentbarn-gateway")).toContainText("Rollout stuck");
    await expect(page.getByTestId("service-agentbarn-gateway")).toContainText("0123456");
  });

  test("lists failing and stalled scheduled jobs first, with when they last worked", async () => {
    const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        cron_jobs: [
          {
            name: "agentbarn-restore-point-schedule",
            schedule: "2-59/5 * * * *",
            state: "failing",
            running: false,
            last_scheduled_at: minutesAgo(3),
            last_successful_at: minutesAgo(6 * 24 * 60),
            last_failed_at: minutesAgo(2),
          },
          {
            name: "agentbarn-cost-sync",
            schedule: "6-59/15 * * * *",
            state: "stalled",
            running: false,
            last_scheduled_at: minutesAgo(40 * 60),
            last_successful_at: minutesAgo(40 * 60),
            last_failed_at: null,
          },
          {
            name: "agentbarn-event-reconciler",
            schedule: "*/5 * * * *",
            state: "ok",
            running: true,
            last_scheduled_at: minutesAgo(1),
            last_successful_at: minutesAgo(4),
            last_failed_at: null,
          },
        ],
      }),
    });

    await healthPage.goto();

    const failing = healthPage.cronJob("agentbarn-restore-point-schedule");
    await expect(failing).toHaveAttribute("data-state", "failing");
    await expect(failing).toContainText("Last run failed");
    await expect(failing).toContainText("last succeeded 6 days ago");
    await expect(healthPage.cronJob("agentbarn-cost-sync")).toContainText("No successful run in over a day");
    await expect(healthPage.cronJob("agentbarn-event-reconciler")).toContainText("Running now");
  });

  test("counts the agents whose scheduled backups fail or are overdue and names the worst", async () => {
    const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
    const ada = {
      agent_id: ENV_ADA_ID,
      agent_name: "Ada",
      organization_id: ENV_ACME_ID,
      organization_name: "Acme",
      status: "RUNNING",
    };
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        backups: {
          enabled: true,
          interval_minutes: 360,
          failure_window_hours: 24,
          running_agents: 58,
          failed_total: 41,
          overdue_total: 12,
          failed: [{ agent: ada, failures: 2, last_failed_at: hoursAgo(1) }],
          overdue: [
            { agent: { ...ada, agent_id: ENV_ORPHAN_ID, agent_name: "Bo" }, last_backup_at: hoursAgo(50) },
            { agent: { ...ada, agent_id: "019f0000-0000-7000-8000-0000000000c1", agent_name: "Cy" }, last_backup_at: null },
          ],
        },
      }),
    });

    await healthPage.goto();

    const backups = healthPage.backups();
    await expect(backups).toContainText("Every 6 hours");
    await expect(backups.getByTestId("backups-summary")).toHaveText(
      "41 of 58 running agents failed a backup in the last 24 hours · 12 more are overdue"
    );
    await expect(backups.getByTestId("backups-more")).toHaveText("and 50 more agents");
    await expect(backups.getByTestId("backup-failed").first()).toContainText("Ada");
    await expect(backups.getByTestId("backup-failed").first()).toContainText("2 failed in the last 24 hours");
    await expect(backups.getByTestId("backup-overdue").first()).toContainText("last backed up 2 days ago");
    await expect(backups.getByTestId("backup-overdue").nth(1)).toContainText("never backed up");
  });

  test("lists agents no one has written to as cleanup candidates, with what they hold", async () => {
    const daysAgo = (days: number) => new Date(Date.now() - days * 86_400_000 - 60_000).toISOString();
    const ada = {
      agent_id: ENV_ADA_ID,
      agent_name: "Ada",
      organization_id: ENV_ACME_ID,
      organization_name: "Acme",
      status: "RUNNING",
    };
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        idle_after_days: 14,
        idle_agents: [
          {
            agent: { ...ada, agent_id: ENV_ORPHAN_ID, agent_name: "Cy", status: "STOPPED" },
            last_user_message_at: null,
            last_call_at: null,
            holds_pod: false,
            volume_claims: 1,
            requested_bytes: GIB,
            restore_points: 0,
            restore_point_bytes: 0,
          },
          {
            agent: ada,
            last_user_message_at: daysAgo(21),
            last_call_at: new Date(Date.now() - 3_600_000).toISOString(),
            holds_pod: true,
            volume_claims: 2,
            requested_bytes: 3 * GIB,
            restore_points: 4,
            restore_point_bytes: 512 * 1024 ** 2,
          },
        ],
      }),
    });

    await healthPage.goto();

    await expect(healthPage.section("idle")).toContainText("no message from anyone in 14 days");
    const [cy, adaRow] = await healthPage.idleAgents().all();
    await expect(cy).toContainText("Cy");
    await expect(cy).toContainText("Never written to");
    await expect(cy).toContainText("1 volume · 1 GiB");
    await expect(adaRow).toContainText("Last message from a person 21 days ago");
    await expect(adaRow).toContainText("Running pod");
    await expect(adaRow).toContainText("2 volumes · 3 GiB");
    await expect(adaRow).toContainText("4 restore points · 512 MiB");
    await expect(adaRow).toContainText("last model call 1 h ago");
  });

  test("says when scheduled backups are switched off", async () => {
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({ backups: { enabled: false, interval_minutes: 0, failed: [], overdue: [] } }),
    });

    await healthPage.goto();

    await expect(healthPage.backups()).toContainText("Scheduled backups are switched off");
  });

  test("says when scheduled jobs may not be read", async () => {
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        sources: [
          { source: "pods", state: "available" },
          { source: "cron_jobs", state: "forbidden" },
        ],
        cron_jobs: [],
      }),
    });

    await healthPage.goto();

    await expect(healthPage.section("scheduled")).toContainText("not permitted for the service account");
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

  test("a line that is quiet now but spiked in the last day says so", async () => {
    await data.environmentHealth.interceptEnvironmentHealth({
      body: mockEnvironmentHealth({
        level: "warning",
        capacity: [
          {
            resource: "limits.cpu",
            unit: "cores",
            source: "entered",
            used: 10,
            hard: 40,
            ratio: 0.25,
            peak: 39.6,
            peak_ratio: 0.99,
            level: "warning",
          },
          {
            resource: "pods",
            unit: "count",
            source: "entered",
            used: 24,
            hard: null,
            ratio: null,
            peak: 31,
            peak_ratio: null,
            level: "unknown",
          },
          { resource: "requests.storage", unit: "bytes", source: "entered", used: GIB, hard: 30 * GIB, ratio: 1 / 30, level: "ok" },
        ],
      }),
    });

    await healthPage.goto();

    await expect(healthPage.capacityLine("limits.cpu")).toContainText("25% of 40 cores");
    await expect(healthPage.capacityPeak("limits.cpu")).toHaveText("24h peak: 39.6 cores (99%)");
    await expect(healthPage.capacityPeak("pods")).toHaveText("24h peak: 31");
    await expect(healthPage.capacityPeak("requests.storage")).toHaveCount(0);
    await expect(healthPage.capacityWarning()).toContainText(
      "limits.cpu reached 99% of its quota in the last 24 hours. Pods starting then may have been refused.",
    );
  });

  test("the quota dialog offers every line and sends only what it shows", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth();
    const sent = await data.resourceUsage.interceptUpdateResourceLimits();

    await healthPage.goto();
    await healthPage.openQuotaDialog();

    await expect(healthPage.quotaInput("requests.storage (GiB)")).toHaveValue("30");
    await expect(healthPage.quotaInput("pods")).toHaveValue("");
    await expect(healthPage.quotaInput("persistentvolumeclaims")).toHaveValue("60");
    await expect(healthPage.quotaInput("services")).toHaveValue("");
    await expect(healthPage.quotaInput("limits.memory (GiB)")).toHaveValue("52");

    await healthPage.quotaInput("pods").fill("2.5");
    await healthPage.saveButton().click();
    await expect(healthPage.dialog()).toContainText("Enter a whole number above 0");
    expect(sent).toEqual([]);

    await healthPage.quotaInput("pods").fill("60");
    await healthPage.quotaInput("requests.storage (GiB)").fill("50");
    await healthPage.quotaInput("services").fill("40");
    await healthPage.saveButton().click();

    await expect(healthPage.dialog()).toBeHidden();
    expect(sent).toEqual([
      {
        requests_storage_bytes: 50 * GIB,
        persistentvolumeclaims: 60,
        pods: 60,
        services: 40,
        limits_memory_bytes: 52 * GIB,
        limits_cpu_cores: 30,
        requests_memory_bytes: 20 * GIB,
        requests_cpu_cores: 5,
      },
    ]);
    await expect(page.getByText("Namespace quota saved")).toBeVisible();
  });

  test("is listed under Overview, which opens the existing overview", async ({ page }) => {
    await data.environmentHealth.interceptEnvironmentHealth();

    await page.goto("/dashboard/platform/event-deliveries");
    const overview = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview", exact: true });
    await expect(overview).toHaveAttribute("href", "/dashboard/platform");
    await expect(
      page.getByRole("complementary").getByRole("link").first(),
    ).toHaveText("Overview");

    await healthPage.goto();
    await expect(healthPage.heading()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Overview/Health");
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
