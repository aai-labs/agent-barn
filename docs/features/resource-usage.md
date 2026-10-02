# Agent Resource Usage

## Read when

Read before changing the Resource usage tab, the Agents overview page, the Platform resource usage page, the CPU and memory series the healthz servers export, the PromQL that reads them, or how the API reaches Prometheus.

## Role in the system

Resource usage answers how much CPU and memory an Agent's container is using, against the limits it runs with. Costs answers what the Agent spent, and Activity answers what it did. This is container usage, not model usage or spend.

Three surfaces show it:

- The **Resource usage** tab on the Agent page: current figures, peak memory, CPU throttling, and charts over 1 hour to 14 days.
- The **Agents overview** at `/dashboard/{org}/agents`, reached from the **Usage** tab in the top nav: every Agent the viewer can read, with status, spend, CPU and memory in the row. A row opens to status, cost and resource usage in full, each linking to its own tab.
- The **Platform Resource Usage** page at `/dashboard/platform/resource-usage`, for Platform Administrators: the same figures across every Organization, as totals, a table by Organization, the heaviest Agents, and two charts. It can be narrowed to one Organization.

The data path has no table of its own:

```text
Agent container  healthz server reads /sys/fs/cgroup ──► /metrics on :8081
Prometheus       `agent` scrape job (helm/monitoring) ──► keeps 15 days
API              resource_usage domain ──► PromQL over HTTP, basic auth
UI               Resource usage tab, Agents overview, Platform Resource Usage
```

## Invariants

- The API stores no usage. Prometheus is the store, and its 15-day retention is the limit, so the longest range is 14 days. The one thing stored is the capacity limits a Platform Administrator enters (see Capacity limits below).
- Each Agent's own healthz server reads the container's cgroup v2 files on every scrape and appends these series to its existing `/metrics`. Both runtimes emit the same series, with the same help text, in the same order; a test compares them.

  | Series | Meaning |
  | --- | --- |
  | `agent_cgroup_metrics_available` | 1 if the files could be read, 0 if not. Always emitted. |
  | `agent_memory_working_set_bytes` | `memory.current` minus `inactive_file`, the same figure `kubectl top` shows. |
  | `agent_memory_limit_bytes` | `memory.max`. Left out when unlimited. |
  | `agent_cpu_usage_seconds_total` | CPU time used (`usage_usec`). |
  | `agent_cpu_limit_cores` | `cpu.max` quota over period. Left out when unlimited. |
  | `agent_cpu_periods_total`, `agent_cpu_throttled_periods_total` | Scheduling periods, and those spent throttled. |

- A series that cannot be read is left out, never guessed, and `/metrics` never fails because of it. `agent_cgroup_metrics_available` is what tells an Agent still running the older script (the gauge is absent) from a host that cannot report (the gauge is 0).
- The read models separate two questions. `availability` is about the source: `available`, `not_configured` (no Prometheus URL), or `unavailable` (it could not be reached). `state` is about one Agent: `reporting`, `restart_required` (scraped, but no usage series yet), `unsupported` (cgroup v2 unreadable), or `no_data`.
- A source that is down is an answer, not an error. Both endpoints return 200 with `availability` set, so the tab can explain itself and the overview keeps status and spend.
- An Agent is found by `app="agent-<agent id>"` and `org_id`, both set by the scrape job from Service labels. The `agent_name` and `org_name` labels are slugs and are not unique, so they are never used to select or match. Selectors are built only from UUIDs that came from the database.
- Permissions follow the figure. Resource usage needs `activity.read` on the Agent, the same as health and runtime diagnostics, and does not need `cost.read`. On the overview each Agent is judged separately: spend needs `cost.read` on that Agent, usage needs `activity.read`. A figure the viewer may not see is `null` and the row stays, so the UI shows a dash, not a missing Agent.
- The overview has no Organization total. That would need the Organization-wide `cost.read`, which an Agent Access Role never grants.
- The overview's spend comes from `CostService.spend_for_agents`, which reads the same `cost_record` predicates as the Agent's own Costs tab, so a row and its cost panel agree. It joins through `agent_scope_predicates`, so an Agent the caller cannot read is absent, not zero.
- A stopped Agent has no container, so it is not queried and its `resource_usage` is `null`.
- The overview lists at most 100 Agents (`OVERVIEW_MAX_AGENTS`) and reports the full count in `total`.
- Platform administrators get no bypass on the Organization routes (see the oversight ADR). They have their own route, below.
- The API reads `PROMETHEUS_PASSWORD` from its own Secret. helmfile sets it from `MONITORING_WEB_PASSWORD` directly, not from the monitoring release's Secret, because that release deploys after the API.
- The scripts ship in the Agent's ConfigMap, so an Agent reports only after it restarts. Editing them changes the runtime digest, so every running Agent shows "update available" until it does.

## Platform view

`GET /api/v1/platform/resource-usage?range=&organization_id=` is behind `require_platform_admin`, with its own service (`PlatformResourceUsageService`) and read models, so the Organization surface has no path to another Organization's figures. Classing this as oversight data is recorded in [`2026-10-01-resource-usage-as-platform-oversight-data.md`](../adr/2026-10-01-resource-usage-as-platform-oversight-data.md).

- It makes one platform-wide instant query (`{job="agent"}`) and one range query, plus one database read of every live Agent. Readings are keyed by the `app` label alone. The Agent, its name and its Organization come from the database, never from the `org_id`, `org_name` or `agent_name` labels, so a wrong label cannot move an Agent or rename an Organization.
- A container that reports but belongs to no live Agent (deleted, or never known here) is not dropped. It becomes its own row with no Organization, listed last and not selectable as a filter, so the Organization rows add up to the platform total and a leaked container is visible. In the Agent table it is named `agent-<first 8 characters of its id>`, enough to find its Deployment.
- A stopped Agent counts as having no container even if a reading arrives for a few minutes after it stops, as on the Organization overview. `agents_with_container` is the database's count of running and errored Agents, so it is there when Prometheus is not.
- The API's Organization list is always platform-wide, whatever the filter, and the page decides how much of it to show: only the selected Organization when one is chosen, otherwise the top five by memory with a note of how many more there are. The no-live-Agent row is kept beside the top five, so it does not use up one of them; a narrowed page leaves it out, as its totals do. Totals, the Agent list and the chart follow the filter. The filtered chart selects by the Agent ids the database places in that Organization, so it counts the Agents the totals count. A deleted Agent's history is in the platform chart but not in an Organization's.
- A Heaviest agents row opens to the same **Status** and **Resource usage** panels the Organization Usage page shows, without the Cost panel and without links, since a Platform Administrator has no Membership and an Organization's agent pages are not theirs to open. One request per opened row, `GET /api/v1/platform/resource-usage/agents/{agent_id}`, refreshed every minute while it stays open, and none for a closed row. Usage covers the last 24 hours, as on the Organization panel, whatever the page's range is.
  - The panels are the same components (`agent-detail-panels.tsx`). Each page reads its own data and hands it in, so they cannot drift in how they look.
  - The response is an explicit allowlist (`PlatformAgentDetailsRead`). It carries the status word only, never the healthz `reason`, and never log text: `AgentService.runtime_restarts` asks the cluster for restarts with `include_logs=False`. An Agent in ERROR shows the fixed-copy summary of its failure, rebuilt from the stored category, never the stored message or detail.
  - A health or cluster read that cannot be answered leaves its fields empty and the rest of the row in place. The Organization route answers 503 for the same cases.
  - A container with no live Agent has no record to show, so its row does not open.
- The chart adds each Agent's highest memory reading in a step and sums them. Agents rarely peak in the same step, so the line can sit a little above the true combined peak, never below it. CPU is the summed five-minute-or-longer rate. There is no throttling series, since a ratio added up across Agents means nothing. Throttling stays per Agent, over the last hour.
- Limits are summed too. They are what the containers may use, which is what the namespace quota counts, not a pool with free room in it.
- The page does not show the namespace quota, volumes or events. That needs the Kubernetes API and belongs to the cluster health page (AF-266).

## Capacity limits

The namespace's ResourceQuota caps the total of every container's **limits**, and a full quota leaves new agents stuck without a pod. The Platform page warns before that. Why the ceilings are typed in, and why this figure, is in [`2026-10-01-capacity-limits-entered-by-hand.md`](../adr/2026-10-01-capacity-limits-entered-by-hand.md).

- A Platform Administrator enters the ceilings in the **Capacity limits** dialog: memory in GiB and CPU in cores, the `limits.memory` and `limits.cpu` Hard values of `kubectl describe quota`. A blank field means no limit, and nothing warns for it. They are saved by `PUT /api/v1/platform/resource-limits` as whole bytes and cores, in the `platform_resource_limits` table, one row at most.
- The same row is read back inside the Platform usage response as `capacity`, with what is committed. There is no separate GET, so there is one place to read them, and the limits are there even when Prometheus is not.
- **Committed** is what every Pending or Running pod in the namespace is allowed to use, added up: `kube_pod_container_resource_limits` joined to `kube_pod_status_phase`, from kube-state-metrics (the `kube-state-metrics` job). It covers the API, UI and database pods as well as the Agents, and Agents that do not report through healthz yet, which is what the quota counts. It is not usage: an agent using 300 MiB with a 2 GiB limit commits 2 GiB. Empty means unknown (`null`), never zero.
- The cards turn amber at 75% of the ceiling and red at 90%, the same constants as the meters (`METER_WARN_RATIO`, `METER_CRITICAL_RATIO`). A figure above 100% is its own state: the quota cannot be exceeded, so it says the entered limit is probably out of date.
- Each change to a limit is a `platform.resource_limits.changed` Security Audit Record, one per limit that moved, with its before and after. A save that changes nothing records nothing. The row is locked while it is read, so two administrators saving at once cannot record the same "previous" value.
- The ceilings are for the whole namespace, so the Organization filter does not change them or the committed figure.
- It does not show pod count, volumes or events. Those need the Kubernetes API and belong to the cluster health page (AF-266).

## Boundaries

The monitoring chart owns Prometheus, the `agent` scrape job and the labels it adds. The healthz scripts own the metric names. The `resource_usage` domain owns the queries and read models. Costs owns spend, and Agents owns health and diagnostics. Resource usage writes nothing and raises no alerts; a memory or throttling alert would be a change to the monitoring chart.

## Known gaps

- "CPU now" is a five-minute rate. Prometheus divides the increase by the whole window, so a series that is only seconds old reads low. In the contract test an Agent using half a core read about 0.003 when it was seconds old. It converges over a few minutes, so a freshly started Agent shows low CPU at first.
- History stops at 14 days, and CPU on the charts is averaged per step, so a short spike is smoothed away. Memory uses the highest reading in each step.
- The overview polls each running row's health every 30 seconds, one request per row. Beyond the 100-Agent cap it would need pagination and a batch health endpoint.
- OpenClaw's Node heap grows toward the 1 GiB limit by design, so high memory is not proof of a leak.
- The usage charts use the reader's local time. The Costs charts use UTC because they bucket by calendar day.
- Hosts without cgroup v2 report `unsupported`.
- There are no Grafana panels or alerts for CPU and memory yet.

## Local development

Local Docker Compose has no Prometheus, so the views say resource usage is not configured until one is installed. `make dev-monitoring` installs the real `helm/monitoring` chart into the k3d cluster (it needs `helm` and `kubectl` on the host) and writes a `PROMETHEUS_PASSWORD` to `.env`. Then run `make forward-prometheus`, recreate the API container, and restart the Agents so they pick up the new script. See the [README](../../README.md#resource-usage-local-prometheus).

## Source map

| Concern                          | Authoritative source |
| -------------------------------- | -------------------- |
| Exported series (Hermes)         | `../../api/domains/agents/scripts/hermes/healthz-server.py` |
| Exported series (OpenClaw)       | `../../api/domains/agents/scripts/openclaw/healthz-server.js` |
| Scrape job and labels            | `../../helm/monitoring/values.yaml` (`job_name: agent`) |
| Prometheus client                | `../../api/infrastructure/prometheus/client.py` |
| Read models, ranges, windows     | `../../api/domains/resource_usage/models.py` |
| PromQL and result mapping        | `../../api/domains/resource_usage/promql.py` |
| Queries against the client       | `../../api/domains/resource_usage/repository.py` |
| Authorization and assembly       | `../../api/domains/resource_usage/service.py` |
| HTTP routes                      | `../../api/domains/resource_usage/routes.py` |
| Capacity limits (stored)         | `../../api/domains/resource_limits/` (`models.py`, `repository.py`, `service.py`, `routes.py`), `../../api/migrations/versions/c7a1e4b92d58_add_platform_resource_limits.py` |
| Committed limits (read)          | `namespace_limits_query` in `../../api/domains/resource_usage/promql.py` |
| Platform view                    | `../../api/domains/resource_usage/platform_service.py`, `../../api/domains/resource_usage/platform_routes.py`, `AgentRepository.find_live_for_platform_usage` in `../../api/domains/agents/repository.py`, `AgentService.agent_health` and `runtime_restarts` in `../../api/domains/agents/service.py`, `ResourceUsageService.usage_for` |
| Spend for a page of Agents       | `CostService.spend_for_agents` in `../../api/domains/costs/service.py` |
| API settings                     | `../../api/core/config.py` (`prometheus_*`), `../../helm/agentbarn-api/values.yaml` (`prometheus`), `../../helmfile.yaml.gotmpl` |
| Local Prometheus                 | `../../docker/k3d/k3d-monitoring.sh`, `../../docker/k3d/monitoring-values.yaml`, `make dev-monitoring`, `make forward-prometheus` |
| UI feature                       | `../../ui/src/features/resource-usage/` (capacity: `components/capacity-section.tsx`, `components/capacity-limits-dialog.tsx`; opened rows: `components/platform-agent-details.tsx`, shared panels in `components/agent-detail-panels.tsx`) |
| UI page and tab wiring           | `../../ui/src/app/dashboard/[orgId]/agents/page.tsx`, `../../ui/src/app/dashboard/platform/resource-usage/page.tsx`, `../../ui/src/features/agents/components/agent-detail-page.tsx`, `../../ui/src/components/top-nav.tsx` |
| Script tests                     | `../../api/tests/unit/test_healthz_server_metrics.py` (both runtimes, parity), `../../hermes-base/test-image.sh`, `../../openclaw-base/test-healthz-metrics.sh` (real images) |
| API tests                        | `../../api/tests/unit/test_prometheus_client.py`, `../../api/tests/unit/test_resource_usage_queries.py`, `../../api/tests/unit/test_platform_resource_usage.py`, `../../api/tests/integration/test_resource_usage.py`, `../../api/tests/integration/test_agent_overview.py`, `../../api/tests/integration/test_platform_resource_usage.py`, `../../api/tests/integration/test_resource_limits.py`, `../../api/tests/integration/test_agent_rbac.py` |
| Contract test (real Prometheus)  | `../../api/tests/integration/test_resource_usage_prometheus_contract.py` |
| UI tests                         | `../../ui/tests/e2e/agent-resource-usage.spec.ts`, `../../ui/tests/e2e/agents-overview.spec.ts`, `../../ui/tests/e2e/platform-resource-usage.spec.ts` |

## Change impact

Renaming a series, or changing its help text or order, touches both healthz scripts, `promql.py`, and the script, query, contract and in-image tests together. Changing the labels the `agent` scrape job adds means changing the selectors. A new read of per-Agent resource data on an Organization route must go through `AgentAuthorization` and be added to the assigned/hidden bypass test in `../../api/tests/integration/test_agent_rbac.py`. A new field on the Platform route is a data-classification decision under the oversight ADR, not an automatic addition. Changing Prometheus retention changes the longest safe range in `ResourceUsageRange`. Changing what `state` means changes the notices in `resource-usage-notice.tsx`. Adding another capacity limit adds a typed nullable column, its change Event setting name, and a card; the committed figure for it must exist in kube-state-metrics.

## Related decisions

- [`2026-09-29-agent-resource-usage-from-prometheus.md`](../adr/2026-09-29-agent-resource-usage-from-prometheus.md)
- [`2026-10-01-resource-usage-as-platform-oversight-data.md`](../adr/2026-10-01-resource-usage-as-platform-oversight-data.md)
- [`2026-10-01-capacity-limits-entered-by-hand.md`](../adr/2026-10-01-capacity-limits-entered-by-hand.md)
- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)
