# Agent Barn rebrand renames everything except Kubernetes namespaces

Status: Accepted
Date: 2026-08-22

The product rebranded from Agent Farm to Agent Barn. The rebrand was applied in layers with different blast radii, and deliberately stopped at the Kubernetes namespace boundary:

- **Prose and docs** say Agent Barn (README, CONTEXT.md, guidelines, architecture, feature docs, UI page titles).
- **Code identifiers** were renamed: `agentbarn_*` metrics (with dashboards, alert rules, and promtool expectations in the same change), the `agentbarn.io/component` Service label domain, Redis namespaces (`agentbarn:events`, `agent-barn.*` locks).
- **Deployment identifiers** were renamed: `helm/agentbarn-{api,ui}` charts and release names, `agentbarn-*` image repositories, the client registry path (`agent-barn/`), local ingress hosts (`*.agentbarn.local`), Grafana dashboard UIDs/tags, and PrometheusRule naming.
- **Frozen on purpose:** the namespaces `agent-farm` / `agent-farm-staging`, their `<namespace>-user` ServiceAccounts, the Postgres app user/db (`agentfarm`), the live `*.k8s.aai-labs.com` domains, and external references to the GitHub repository (`aai-labs/agent-farm`).

## Considered alternatives

- **Rename everything at once, including namespaces.** Rejected: moving running workloads to a new namespace means recreating every agent Deployment/PVC/Service (agents run RWC PVCs), re-bootstrapping RBAC and Postgres, and a coordinated prod+staging outage window. The product benefit is cosmetic; the operational cost is not.
- **Freeze all deployment identifiers** (charts, images, DB included). Rejected: unlike namespaces, chart/release/image names can be migrated with rolling deploys — new releases install alongside old ones, get verified, and the old releases are uninstalled. Freezing them would leave the codebase permanently split-branded for no saved risk.
- **Keep the old metric names** to preserve Prometheus history. Rejected: metric history continuity was judged worth less than never carrying an `agentfarm_` prefix again; alert rules were updated in the same diff so no alert silently broke.

## Consequences

- Two naming vocabularies coexist: anything provisioned *inside* the cluster says `agentbarn`; the namespace layer says `agent-farm`. New work must not "fix" namespace strings casually — they are load-bearing (see [`../guidelines/operations.md`](../guidelines/operations.md) naming note).
- Deploying the renamed releases creates NEW helm releases (`agentbarn-api/ui`) next to the legacy ones; the cutover runbook is: push `agentbarn-*` images → deploy → verify → uninstall `agentfarm-api`/`agentfarm-ui`.
- Existing agent Services keep the legacy `agentfarm.io/component` label until relabeled or recreated. Prometheus discovers agents via Service labels only, so they can be patched in place without restarting agents: `kubectl -n <namespace> label svc -l agentfarm.io/component=agent agentbarn.io/component=agent --overwrite` (see operations.md).
- Renamed metrics do not inherit Prometheus history; rate-based alerts have a warm-up gap of one scrape-window after cutover.
- `Config.ingest_base_url` (the URL agents use to reach the API's ingest endpoint) still defaults to the legacy `agentfarm-api` Service. It is deliberately not renamed in this change: the `agentbarn-api` Service does not exist until the new release is deployed, and running agents read this at request time, so flipping it early would break ingest before cutover. Update it alongside the runbook's "uninstall `agentfarm-api`" step, not before.
- A future namespace migration (if ever) should be its own ADR with a workload-by-workload move plan.
