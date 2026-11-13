# Environment Health

## Read when

Read before changing the Platform environment health endpoint, what it reads from the cluster, Prometheus or the database, how it classifies pods, volume claims, CronJobs, Deployments' builds and Events, the quota ceilings it compares with, the idle-Agent rule, or the Kubernetes permissions the API relies on for them.

## Role in the system

Environment health answers whether the namespace the platform runs in can run Agents: are the platform's own services up and on the build that was deployed, is any quota near full now or was it in the last day, which pods are failing or keep restarting, whether the scheduled jobs and backups run, which Agents' runtimes are unhealthy, which Agents sit idle holding resources, and what the cluster has been warning about. It is for Platform Administrators and needs no cluster access. Resource usage answers how much CPU and memory each Agent uses; this page answers what is stopping the namespace from working.

`GET /api/v1/platform/environment-health` is behind `require_platform_admin`, with its own service (`EnvironmentHealthService`) and read model (`EnvironmentHealthRead`). It is classed as Platform Oversight Data in [`2026-10-20-environment-health-as-platform-oversight-data.md`](../adr/2026-10-20-environment-health-as-platform-oversight-data.md), which also lists what the read model may and may not carry; [`2026-11-12-environment-health-history-schedules-and-idle-agents.md`](../adr/2026-11-12-environment-health-history-schedules-and-idle-agents.md) classifies the peaks, restart history, builds, scheduled jobs, backups and idle Agents.

## Sources

Everything comes from the one namespace the API manages (`K8S_NAMESPACE`), where the platform's services and the Agents both run, plus the in-namespace Prometheus and the database.

| Source | Read | Gives |
| --- | --- | --- |
| `pods` | list pods | Workload issues, pods counted against the `pods` quota line, whether each Agent's pod is ready |
| `deployments` | list Deployments | The platform's services (API, UI, workers, LiteLLM, Redis, ...), their ready replicas, `build-sha` annotation and rollout state |
| `stateful_sets` | list StatefulSets | The databases' ready replicas |
| `volume_claims` | list PersistentVolumeClaims | Storage by group, storage counted against `requests.storage`, claims counted against `persistentvolumeclaims` |
| `services` | list Services | Services counted against the `services` quota line |
| `cron_jobs` | list CronJobs | The platform's scheduled jobs: schedule, suspended, last schedule and last success |
| `jobs` | list Jobs | Each CronJob's finished runs, failed or complete, by condition type and time |
| `resource_quotas` | list ResourceQuotas | The quota's own figures, when the account may read them |
| `events` | list Events with `type=Warning` | Recent warnings, explained |
| `prometheus` | `ALERTS{alertstate="firing"}`, the Agents' `agent_healthz_ok` and `agent_healthz_ever_connected`, kube-state-metrics' restart counter and last termination reason over 7 days, and the namespace's commitments and live pod count over 24 hours | Firing alerts, unhealthy runtimes, restart history, capacity peaks |
| database | restore points, chat messages, cost records | Failing and overdue scheduled backups; when a person last wrote to each Agent, its last model call and its restore points, for idle Agents |

The API already lists pods, Deployments and claims to run Agents, so those reads work on the shared cluster today. The tenant chart's `workspace-maintainer` Role, which this repository does not hold, also lets the account list Services, CronJobs, Jobs, StatefulSets, ReplicaSets and Events (checked with `kubectl auth can-i --list` in `agent-farm` and `agent-farm-staging`, Nov 2026). It has no `resourcequotas` rule ([capacity limits ADR](../adr/2026-10-01-capacity-limits-entered-by-hand.md)). The database parts need no cluster read at all.

## Invariants

- **Read-only.** Nothing on this route creates, changes, restarts or deletes a cluster resource, or stops or deletes an Agent.
- **Every source is optional.** Each is read on its own and its state is reported in `sources`: `available`, `forbidden` (the cluster answered 403), `unavailable` (any other failure, logged with its exception), or `not_configured` (no cluster or no Prometheus URL, as in local Docker Compose). Kubernetes list reads have a ten-second request timeout. A source that fails leaves its part empty; the rest of the page still renders and the route still answers 200.
- **No cluster text reaches a client.** Event messages, container messages, Job and Deployment condition messages, alert annotations and log lines are never carried, nor a restore point's `failure_reason` or any message content. A build is kept only as 7–40 hex characters and a CronJob schedule only in the cron grammar. A Warning Event gets a fixed explanation for its reason. A complete quota or LimitRange rejection is rebuilt into a detail by `cluster_rejection_detail`, held to the same grammar as a provisioning failure's detail. Reasons, phases and alert severities are kept only when they match a fixed list or shape; anything else reads as `Unknown` or `null`.
- **Agents are named from the database.** A resource belongs to an Agent when a label this platform sets (`app=agent-<id>`, or `agentbarn.io/agent-id` on restore-point resources) carries its id; the name, status and Organization come from the database. The `org-id`, `agent_name` and `org_name` labels are never used. An id with no live Agent shows as that id alone.
- **Quota names are not carried.** Two quotas capping the same resource show as one line, the one nearer its limit. A quota line scoped to a storage class or any other custom name is left out.

## What the page shows

- **Services.** The platform's own Deployments and StatefulSets: anything that is not an Agent's (`app=agent-<id>` or `agentbarn.io/component=agent`) or a restore point's (`agentbarn.io/component=restore-point`). Critical with no ready replica, a warning with fewer than desired, fine when scaled to zero. A Deployment also carries its `build-sha` pod-template annotation (set from `GIT_SHA` by `deploy.yml` through the charts' `buildSha` value) and its rollout state from the `Progressing` condition's reason: complete (`NewReplicaSetAvailable`, with the condition's `lastUpdateTime` as when it finished), stuck (`ProgressDeadlineExceeded`, a warning) or in progress.
- **Deployed build.** The build of the Deployment whose rollout finished last, how long ago, and the services on another build. Services left on another build with no rollout under way are a warning: a deploy that stopped landing shows as an old build and an old date.
- **Scheduled jobs.** The platform's CronJobs, failing and stalled first. Failing when the newest finished run Kubernetes keeps (by the Job's owner reference) failed; stalled when, not suspended, nothing succeeded for 24 hours, or never, once the CronJob is a day old. Every platform CronJob runs at least hourly, so a day is a stall whatever the schedule. Either is a warning.
- **Agent backups.** From the database: running Agents whose scheduled restore points failed in the last 24 hours, and running Agents at least two intervals old whose newest READY scheduled restore point is older than two intervals (`RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES`, so 12 hours by default). Either is a warning. The page leads with how many running Agents fail and how many more are overdue, then names only the worst five of each (most failures first; never backed up, then longest without a backup) and counts the rest, so a failure across the platform, such as a full volume-claim quota, reads as one problem rather than a list of every Agent. An Agent that fails and is overdue is counted and named once, as failing. With the schedule off (interval 0), the page says so and lists nothing.
- **Capacity.** One line per quota resource, storage, claims, pods and Services first, since those stop new Agents.
  - When the ResourceQuota can be read and the namespace has one, its `hard` and `used` figures are the answer (`source: quota`).
  - Otherwise each line is a ceiling a Platform Administrator entered (`source: entered`) beside what the API counts: `requests.storage` is every claim's request added up, terminating ones included; `persistentvolumeclaims` and `services` are every claim and every Service in the namespace; `pods` is every pod not Succeeded or Failed; CPU and memory are what the pods commit, from kube-state-metrics, as on the Platform Resource Usage page. The ceilings are the `platform_resource_limits` row (see [resource usage](resource-usage.md#namespace-quota)).
  - **Peaks.** CPU, memory and pod lines carry the highest figure of the last 24 hours (`peak_window_hours`): `max_over_time` over the same commitment query, and over the count of Pending or Running pods, sampled every 30 seconds, the scrape interval, so a minute-long burst of cron jobs lands in at least one sample. Storage, claims and Services have no history and no peak. A peak that cannot be read is left out; the current figures still show.
  - Levels: `warning` at 75% and `critical` at 90%, the same as the resource usage meters; a line below that whose peak reached 90% is a `warning`, since a pod starting then would have been refused; `ceiling_out_of_date` when an entered ceiling is exceeded, since the quota cannot be; `unknown` with no ceiling or nothing to compare it with. A peak never lowers a level. A quota of zero is critical and takes precedence over any nonzero quota for the same resource.
- **Volumes.** Every claim, grouped as `infrastructure` (no Agent or restore-point label), `active_agents`, `stopped_agents`, `restore_points` and `orphaned` (an Agent's claim whose Agent is not live), with counts and requested bytes. An Agent's claim is recognized by its `app=agent-<id>` label, since claims are never relabelled and older ones carry the pre-rebrand `agentfarm.io/component` label or none. Orphaned claims and claims that are not Bound are listed.
- **Workloads.** Pod counts, and the pods that need a look: Failed, unschedulable, waiting on a crash loop or an image that will not pull, restarting repeatedly, OOM-killed in the last 7 days (`restart_window_days`), or not ready two minutes after starting. A finished Job's pod is not counted. A failed pod of a CronJob's run is left out when the CronJobs could be read, since Scheduled jobs already shows that job failing. Platform pods are listed before Agents', then the most restarts.
  - With the restart history (kube-state-metrics' `kube_pod_container_status_restarts_total` increase and `kube_pod_container_status_last_terminated_reason="OOMKilled"` over 7 days), a pod restarting three times or more in the window is listed however long ago the last restart was, and `restarts_in_window` is its count. A container OOM-killed once a day never restarts three times in an hour, so the hour rule missed it.
  - A pod the history does not cover, or every pod when Prometheus cannot answer, is judged by the pod alone: three restarts in its life with the last in the past hour, since restart counts never reset and a pod that restarted when its node rebooted and has run cleanly since should not be listed; and an `OOMKilled` last termination in the last 7 days.
- **Unhealthy runtimes.** Agents whose healthz reports `agent_healthz_ok` 0, with whether their pod is ready and whether the runtime ever connected. A stopped Agent's lingering reading is left out.
- **Failed Agents.** Every live Agent in ERROR, with its stored failure's fixed-copy summary, code and detail.
- **Idle Agents.** Running or stopped Agents at least 14 days old (`idle_after_days`) that no person has written to in 14 days, never-used first, as cleanup candidates. Only an inbound chat message counts as use: the platform wakes Agents on its own (heartbeats, schedules, platform-wide restarts such as Oct 27's), so cost records cannot tell use from a wake; the last model call is shown for context and never decides. Each row shows what it holds: whether it has a pod, its volume claims (its own and its restore points', by the Agent id in their labels) and their requested size, and its READY restore points and their archive size. Covers Hermes and OpenClaw alike, since none of it depends on the runtime. Idle Agents do not change the level.
- **Events.** Warning Events from the last six hours, newest first. Events about the pods, ReplicaSets or Jobs of a Deployment, StatefulSet or CronJob (an Agent's included) read as about that workload, matched by name since an Event does not carry its object's owner and a CronJob's old runs are deleted before their Events expire, so a CronJob failing every run is one row with a count rather than a row per run.
- **Alerts.** The monitoring chart's firing alerts by name and severity, with the Agent for an Agent's alert. Rules with the same name and Agent are combined at their highest firing severity. The alert and runtime queries are read separately, so one failing keeps what the other returned.
- **Level.** `critical` when a service has no ready replica, a capacity line is critical, or a critical alert fires; `warning` for anything else listed, including a stuck rollout, services left on another build, a failing or stalled CronJob, failing or overdue backups, orphaned or unbound claims and recent Warning Events, and when Prometheus is `unavailable`, since a critical alert may be firing unseen; `unknown` when neither pods nor Deployments could be read; otherwise `ok`. Idle Agents never raise it.
- **Ceilings.** The `platform_resource_limits` row as entered (`ceilings`), whichever source the capacity lines came from, so the page can edit it.

## The page

`/dashboard/platform/environment-health`, behind `PlatformAdminOnly`, polls the endpoint every minute. It shows the level, a line naming every source that could not be read, then Capacity with each line's 24-hour peak, Platform services with the deployed build and firing alerts, Agents needing attention, Scheduled jobs with Agent backups, Workloads, Idle agents, Storage and Recent warnings. A part whose source is missing says why ("not permitted for the service account") rather than showing an empty list, so a missing part is never read as "all clear". Every list that grows with the platform (Agents needing attention, Agent backups, Workloads, Idle agents, the claims under Storage and Recent warnings) shows its first five rows and the rest behind "Show all"; the response carries how many rows each has (`totals`, and the backups' own counts) and at most 100 of them (`LIST_LIMIT`), worst first, and the page says "Showing 100 of N" past that. The level is worked out from every row, not only those carried.

- Agents are shown by name with their Organization, which links to the Organization's Platform page, never to the Organization's own Agent pages: a Platform Administrator has no Membership there.
- **Namespace quota** opens the same dialog as the Platform Resource Usage page, with all eight lines. Each page sends only the lines it shows, so saving CPU and memory there leaves storage and pods as they are. Saving refreshes both pages.
- It is listed first under System in Platform View, so the rail's System button opens it.

## Known gaps

- The tenant account cannot read the ResourceQuota, so capacity normally rests on entered ceilings, which go stale when the cluster's owners change the quota.
- Events may be refused on the shared cluster. The page then says so and relies on the failed Agents' stored failures.
- Kubernetes keeps Events for about an hour by default, so older warnings are gone whatever the window.
- History is limited to what Prometheus keeps (15 days): capacity peaks over 24 hours for CPU, memory and pods, and restarts over 7 days. Storage, claims and Services have none. A burst shorter than one 30-second scrape can still fall between samples.
- A CronJob's failures are only those Kubernetes still keeps (its `failedJobsHistoryLimit`, 1 by default), so the page shows the newest outcome and the last failure, not a failure count.
- An Agent used only through something other than chat (a workflow, a schedule it runs for a person) has no inbound messages and is listed as idle. The last model call beside it is the hint.
- A claim's size is its request, which is what the quota charges, not what the volume holds.

## Source map

| Concern | Authoritative source |
| --- | --- |
| Read models | `../../api/domains/environment_health/models.py` |
| Classification and allowlists | `../../api/domains/environment_health/cluster.py` |
| Cluster and Prometheus reads | `../../api/domains/environment_health/repository.py` (`restart_history_query`), `../../api/infrastructure/kubernetes/client.py` (`list_pods`, `list_stateful_sets`, `list_services`, `list_cron_jobs`, `list_namespace_jobs`, `list_resource_quotas`, `list_warning_events`) |
| Capacity peaks | `namespace_peak_commitments_query` and `namespace_peak_pods_query` in `../../api/domains/resource_usage/promql.py`; `PlatformResourceUsageService.namespace_peaks` |
| Scheduled backups | `RestorePointService.scheduled_backup_health`, `find_scheduled_failures_since` and `find_overdue_scheduled_backups` in `../../api/domains/restore_points/` |
| Idle Agents | `idle_agents` in `cluster.py`; `ConversationService.latest_inbound_times_for_platform`, `ActivityService.latest_call_times_for_platform`, `RestorePointService.ready_totals_for_platform` |
| Assembly, source states and level | `../../api/domains/environment_health/service.py` |
| HTTP route | `../../api/domains/environment_health/routes.py` |
| Event and failure detail grammar | `cluster_rejection_detail` and `persisted_provisioning_error` in `../../api/domains/agents/provisioning_errors.py` |
| Failed Agents | `AgentRepository.find_failed_for_platform` in `../../api/domains/agents/repository.py` |
| Storage, claim, pod and Service ceilings | `../../api/domains/resource_limits/`, `../../api/migrations/versions/70a78f958eb7_capacity_limits_storage_and_pods.py`, `../../api/migrations/versions/b3d81c5e9f42_capacity_limits_claims_and_services.py` |
| CPU and memory committed | `PlatformResourceUsageService.namespace_capacity` in `../../api/domains/resource_usage/platform_service.py` |
| UI feature | `../../ui/src/features/environment-health/`; the shared quota dialog in `../../ui/src/features/resource-usage/components/capacity-limits-dialog.tsx` |
| UI route | `../../ui/src/app/dashboard/platform/environment-health/page.tsx` |
| Tests | `../../api/tests/unit/test_environment_health_cluster.py`, `../../api/tests/integration/test_environment_health.py`, `../../api/tests/integration/test_resource_limits.py`, `../../api/tests/integration/test_resource_usage_prometheus_contract.py` (peaks and restart history against a real Prometheus), `../../ui/tests/e2e/platform-environment-health.spec.ts` |

## Change impact

A new field on the read model is a data-classification decision under the environment health ADRs. A new reason, phase or object kind is an addition to an allowlist in `cluster.py` and its tests. Changing how an Agent's resources are labelled (`../../api/domains/agents/builders/common.py`, `restore_point.py`) changes how claims and pods are grouped here. Changing the quota thresholds changes them on both this page and the resource usage meters. Changing the monitoring chart's scrape interval should change the peak step (`_PEAK_STEP_SECONDS`) with it. A chart that stops setting `build-sha` leaves its service with no build. A platform CronJob scheduled less often than daily would read as stalled. A new Kubernetes read needs a matching rule for the tenant account on the shared cluster, or it shows as `forbidden` there.

## Related decisions

- [`2026-10-20-environment-health-as-platform-oversight-data.md`](../adr/2026-10-20-environment-health-as-platform-oversight-data.md)
- [`2026-11-12-environment-health-history-schedules-and-idle-agents.md`](../adr/2026-11-12-environment-health-history-schedules-and-idle-agents.md)
- [`2026-10-01-capacity-limits-entered-by-hand.md`](../adr/2026-10-01-capacity-limits-entered-by-hand.md)
- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)
