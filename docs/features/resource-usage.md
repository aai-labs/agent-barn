# Agent Resource Usage

## Read when

Read before changing the Resource usage tab, the Agents overview page, the CPU and memory series the healthz servers export, the PromQL that reads them, or how the API reaches Prometheus.

## Role in the system

Resource usage answers how much CPU and memory an Agent's container is using, against the limits it runs with. Costs answers what the Agent spent, and Activity answers what it did. This is container usage, not model usage or spend.

Two surfaces show it:

- The **Resource usage** tab on the Agent page: current figures, peak memory, CPU throttling, and charts over 1 hour to 14 days.
- The **Agents overview** at `/dashboard/{org}/agents`, reached from the **Usage** tab in the top nav: every Agent the viewer can read, with status, spend, CPU and memory in the row. A row opens to status, cost and resource usage in full, each linking to its own tab.

The data path has no table of its own:

```text
Agent container  healthz server reads /sys/fs/cgroup ──► /metrics on :8081
Prometheus       `agent` scrape job (helm/monitoring) ──► keeps 15 days
API              resource_usage domain ──► PromQL over HTTP, basic auth
UI               Resource usage tab, Agents overview
```

## Invariants

- The API stores nothing. Prometheus is the store, and its 15-day retention is the limit, so the longest range is 14 days.
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
- Platform administrators get no bypass on these routes (see the oversight ADR). A cross-organization Agent list is separate work (AF-250).
- The API reads `PROMETHEUS_PASSWORD` from its own Secret. helmfile sets it from `MONITORING_WEB_PASSWORD` directly, not from the monitoring release's Secret, because that release deploys after the API.
- The scripts ship in the Agent's ConfigMap, so an Agent reports only after it restarts. Editing them changes the runtime digest, so every running Agent shows "update available" until it does.

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
| Spend for a page of Agents       | `CostService.spend_for_agents` in `../../api/domains/costs/service.py` |
| API settings                     | `../../api/core/config.py` (`prometheus_*`), `../../helm/agentbarn-api/values.yaml` (`prometheus`), `../../helmfile.yaml.gotmpl` |
| Local Prometheus                 | `../../docker/k3d/k3d-monitoring.sh`, `../../docker/k3d/monitoring-values.yaml`, `make dev-monitoring`, `make forward-prometheus` |
| UI feature                       | `../../ui/src/features/resource-usage/` |
| UI page and tab wiring           | `../../ui/src/app/dashboard/[orgId]/agents/page.tsx`, `../../ui/src/features/agents/components/agent-detail-page.tsx`, `../../ui/src/components/top-nav.tsx` |
| Script tests                     | `../../api/tests/unit/test_healthz_server_metrics.py` (both runtimes, parity), `../../hermes-base/test-image.sh`, `../../openclaw-base/test-healthz-metrics.sh` (real images) |
| API tests                        | `../../api/tests/unit/test_prometheus_client.py`, `../../api/tests/unit/test_resource_usage_queries.py`, `../../api/tests/integration/test_resource_usage.py`, `../../api/tests/integration/test_agent_overview.py`, `../../api/tests/integration/test_agent_rbac.py` |
| Contract test (real Prometheus)  | `../../api/tests/integration/test_resource_usage_prometheus_contract.py` |
| UI tests                         | `../../ui/tests/e2e/agent-resource-usage.spec.ts`, `../../ui/tests/e2e/agents-overview.spec.ts` |

## Change impact

Renaming a series, or changing its help text or order, touches both healthz scripts, `promql.py`, and the script, query, contract and in-image tests together. Changing the labels the `agent` scrape job adds means changing the selectors. A new read of per-Agent resource data must go through `AgentAuthorization` and be added to the assigned/hidden bypass test in `../../api/tests/integration/test_agent_rbac.py`. Changing Prometheus retention changes the longest safe range in `ResourceUsageRange`. Changing what `state` means changes the notices in `resource-usage-notice.tsx`.

## Related decisions

- [`2026-09-29-agent-resource-usage-from-prometheus.md`](../adr/2026-09-29-agent-resource-usage-from-prometheus.md)
- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)
