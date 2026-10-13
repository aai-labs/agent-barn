# Read Agent resource usage from Prometheus, exported by each Agent itself

Status: Accepted
Date: 2026-09-29
Origin: AF-170

The product needs each Agent's CPU and memory, with history. Each Agent's healthz server reads its own container's cgroup v2 files and adds them to the `/metrics` page our namespace-scoped Prometheus already scrapes, and the API queries that Prometheus over HTTP with the monitoring basic-auth password. It works with the permissions the tenant deployer already has, and needs no new cluster access.

## Considered alternatives

- **metrics-server through the Kubernetes API.** Production has it, but the tenant account (`agent-farm-user`) is forbidden from `pods.metrics.k8s.io`, and the tenant deployer cannot create RBAC on the shared cluster, so the grant would have to come from the cluster owners. It also keeps only the latest reading, so history would need a second store.
- **kubelet and cAdvisor scraping, as in kube-prometheus-stack.** This needs node-level access, which is why AF-222 replaced that stack with plain namespace-scoped charts. Our Prometheus has no container CPU or memory for the same reason.
- **Push samples to Ingest and store them in Postgres,** following [push-based runtime telemetry](2026-07-17-push-based-runtime-telemetry.md). It would need no monitoring stack and would let us choose retention, but it needs a new table, a migration and a pruning job, and it would rebuild storage and querying that Prometheus already provides for the health metrics.

## Consequences

- An Agent reports only after it restarts on the new script. Until then the views say a restart is needed.
- History is limited by Prometheus retention (15 days), so charts stop at 14 days.
- The product API now depends on the monitoring release for a feature. It degrades to "unavailable" or "not configured" and never fails a request.
- The API holds the `monitoring` password, which can read every metric in the namespace. It already has full database access, so this adds no new exposure of tenant data.

## Revisit when

The cluster's own monitoring stack (`aai-labs/k3s-hetzner-cluster-infra`) keeps kubelet scraping on and retains 90 days, so it probably already has these figures for our pods. If the platform owners allow our API to query it, the data source could switch to its `container_*` series. The API, read models and UI would stay; only the queries and credentials would change, and the exported series and the local Prometheus setup could be retired.
