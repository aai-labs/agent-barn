# Environment Health

## Read when

Read before changing the Platform environment health endpoint, what it reads from the cluster or Prometheus, how it classifies pods, volume claims and Events, the storage and pod-count quota ceilings, or the Kubernetes permissions the API relies on for them.

## Role in the system

Environment health answers whether the namespace the platform runs in can run Agents: are the platform's own services up, is any quota near full, which pods are failing, which Agents' runtimes are unhealthy, and what the cluster has been warning about. It is for Platform Administrators and needs no cluster access. Resource usage answers how much CPU and memory each Agent uses; this page answers what is stopping the namespace from working.

`GET /api/v1/platform/environment-health` is behind `require_platform_admin`, with its own service (`EnvironmentHealthService`) and read model (`EnvironmentHealthRead`). It is classed as Platform Oversight Data in [`2026-10-20-environment-health-as-platform-oversight-data.md`](../adr/2026-10-20-environment-health-as-platform-oversight-data.md), which also lists what the read model may and may not carry.

## Sources

Everything comes from the one namespace the API manages (`K8S_NAMESPACE`), where the platform's services and the Agents both run, plus the in-namespace Prometheus and the database.

| Source | Read | Gives |
| --- | --- | --- |
| `pods` | list pods | Workload issues, pods counted against the `pods` quota line, whether each Agent's pod is ready |
| `deployments` | list Deployments | The platform's services (API, UI, workers, LiteLLM, Redis, ...) and their ready replicas |
| `stateful_sets` | list StatefulSets | The databases' ready replicas |
| `volume_claims` | list PersistentVolumeClaims | Storage by group, storage counted against `requests.storage` |
| `resource_quotas` | list ResourceQuotas | The quota's own figures, when the account may read them |
| `events` | list Events with `type=Warning` | Recent warnings, explained |
| `prometheus` | `ALERTS{alertstate="firing"}`, the Agents' `agent_healthz_ok` and `agent_healthz_ever_connected` | Firing alerts, unhealthy runtimes |

The API already lists pods, Deployments and claims to run Agents, so those reads work on the shared cluster today. The tenant account has no `resourcequotas` rule ([capacity limits ADR](../adr/2026-10-01-capacity-limits-entered-by-hand.md)); whether it may read StatefulSets and Events depends on the cluster's tenant chart, which this repository does not hold.

## Invariants

- **Read-only.** Nothing on this route creates, changes, restarts or deletes a cluster resource.
- **Every source is optional.** Each is read on its own and its state is reported in `sources`: `available`, `forbidden` (the cluster answered 403), `unavailable` (any other failure, logged with its exception), or `not_configured` (no cluster or no Prometheus URL, as in local Docker Compose). A source that fails leaves its part empty; the rest of the page still renders and the route still answers 200.
- **No cluster text reaches a client.** Event messages, container messages, alert annotations and log lines are never carried. A Warning Event gets a fixed explanation for its reason. A complete quota or LimitRange rejection is rebuilt into a detail by `cluster_rejection_detail`, held to the same grammar as a provisioning failure's detail. Reasons, phases and alert severities are kept only when they match a fixed list or shape; anything else reads as `Unknown` or `null`.
- **Agents are named from the database.** A resource belongs to an Agent when a label this platform sets (`app=agent-<id>`, or `agentbarn.io/agent-id` on restore-point resources) carries its id; the name, status and Organization come from the database. The `org-id`, `agent_name` and `org_name` labels are never used. An id with no live Agent shows as that id alone.
- **Quota names are not carried.** Two quotas capping the same resource show as one line, the one nearer its limit. A quota line scoped to a storage class or any other custom name is left out.

## What the page shows

- **Services.** The platform's own Deployments and StatefulSets (anything not labelled `agentbarn.io/component` `agent` or `restore-point`). Critical with no ready replica, a warning with fewer than desired, fine when scaled to zero.
- **Capacity.** One line per quota resource, storage and pods first, since those stop new Agents.
  - When the ResourceQuota can be read and the namespace has one, its `hard` and `used` figures are the answer (`source: quota`).
  - Otherwise each line is a ceiling a Platform Administrator entered (`source: entered`) beside what the API counts: `requests.storage` is every claim's request added up, terminating ones included; `pods` is every pod not Succeeded or Failed; CPU and memory are what the pods commit, from kube-state-metrics, as on the Platform Resource Usage page. The ceilings are the `platform_resource_limits` row (see [resource usage](resource-usage.md#namespace-quota)).
  - Levels: `warning` at 75% and `critical` at 90%, the same as the resource usage meters; `ceiling_out_of_date` when an entered ceiling is exceeded, since the quota cannot be; `unknown` with no ceiling or nothing to compare it with. A quota of zero is critical.
- **Volumes.** Every claim, grouped as `infrastructure` (no platform label), `active_agents`, `stopped_agents`, `restore_points` and `orphaned` (an Agent's claim whose Agent is not live), with counts and requested bytes. Orphaned claims and claims that are not Bound are listed.
- **Workloads.** Pod counts, and the pods that need a look: Failed, unschedulable, waiting on a crash loop or an image that will not pull, restarted three times or more with the last restart in the past hour, or not ready two minutes after starting. Restart counts never reset, so a pod that restarted when its node rebooted and has run cleanly since is not listed. A finished Job's pod is not counted. Platform pods are listed before Agents'.
- **Unhealthy runtimes.** Agents whose healthz reports `agent_healthz_ok` 0, with whether their pod is ready and whether the runtime ever connected. A stopped Agent's lingering reading is left out.
- **Failed Agents.** Every live Agent in ERROR, with its stored failure's fixed-copy summary, code and detail.
- **Events.** Warning Events from the last six hours, newest first, at most 50.
- **Alerts.** The monitoring chart's firing alerts by name and severity, with the Agent for an Agent's alert.
- **Level.** `critical` when a service has no ready replica, a capacity line is critical, or a critical alert fires; `warning` for anything else listed; `unknown` when neither pods nor Deployments could be read; otherwise `ok`.
- **Ceilings.** The `platform_resource_limits` row as entered (`ceilings`), whichever source the capacity lines came from, so the page can edit it.

## The page

`/dashboard/platform/environment-health`, behind `PlatformAdminOnly`, polls the endpoint every minute. It shows the level, a line naming every source that could not be read, then Capacity, Platform services with firing alerts, Agents needing attention, Workloads, Storage and Recent warnings. A part whose source is missing says why ("not permitted for the service account") rather than showing an empty list, so a missing part is never read as "all clear".

- Agents are shown by name with their Organization, which links to the Organization's Platform page, never to the Organization's own Agent pages: a Platform Administrator has no Membership there.
- **Namespace quota** opens the same dialog as the Platform Resource Usage page, with all six lines. Each page sends only the lines it shows, so saving CPU and memory there leaves storage and pods as they are. Saving refreshes both pages.
- It is listed first under System in Platform View, so the rail's System button opens it.

## Known gaps

- The tenant account cannot read the ResourceQuota, so capacity normally rests on entered ceilings, which go stale when the cluster's owners change the quota.
- Events may be refused on the shared cluster. The page then says so and relies on the failed Agents' stored failures.
- Kubernetes keeps Events for about an hour by default, so older warnings are gone whatever the window.
- There is no history: every figure is as of `observed_at`.
- A claim's size is its request, which is what the quota charges, not what the volume holds.

## Source map

| Concern | Authoritative source |
| --- | --- |
| Read models | `../../api/domains/environment_health/models.py` |
| Classification and allowlists | `../../api/domains/environment_health/cluster.py` |
| Cluster and Prometheus reads | `../../api/domains/environment_health/repository.py`, `../../api/infrastructure/kubernetes/client.py` (`list_pods`, `list_stateful_sets`, `list_resource_quotas`, `list_warning_events`) |
| Assembly, source states and level | `../../api/domains/environment_health/service.py` |
| HTTP route | `../../api/domains/environment_health/routes.py` |
| Event and failure detail grammar | `cluster_rejection_detail` and `persisted_provisioning_error` in `../../api/domains/agents/provisioning_errors.py` |
| Failed Agents | `AgentRepository.find_failed_for_platform` in `../../api/domains/agents/repository.py` |
| Storage and pod ceilings | `../../api/domains/resource_limits/`, `../../api/migrations/versions/70a78f958eb7_capacity_limits_storage_and_pods.py` |
| CPU and memory committed | `PlatformResourceUsageService.namespace_capacity` in `../../api/domains/resource_usage/platform_service.py` |
| UI feature | `../../ui/src/features/environment-health/`; the shared quota dialog in `../../ui/src/features/resource-usage/components/capacity-limits-dialog.tsx` |
| UI route | `../../ui/src/app/dashboard/platform/environment-health/page.tsx` |
| Tests | `../../api/tests/unit/test_environment_health_cluster.py`, `../../api/tests/integration/test_environment_health.py`, `../../api/tests/integration/test_resource_limits.py`, `../../ui/tests/e2e/platform-environment-health.spec.ts` |

## Change impact

A new field on the read model is a data-classification decision under the environment health ADR. A new reason, phase or object kind is an addition to an allowlist in `cluster.py` and its tests. Changing how an Agent's resources are labelled (`../../api/domains/agents/builders/common.py`, `restore_point.py`) changes how claims and pods are grouped here. Changing the quota thresholds changes them on both this page and the resource usage meters. A new Kubernetes read needs a matching rule for the tenant account on the shared cluster, or it shows as `forbidden` there.

## Related decisions

- [`2026-10-20-environment-health-as-platform-oversight-data.md`](../adr/2026-10-20-environment-health-as-platform-oversight-data.md)
- [`2026-10-01-capacity-limits-entered-by-hand.md`](../adr/2026-10-01-capacity-limits-entered-by-hand.md)
- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)
