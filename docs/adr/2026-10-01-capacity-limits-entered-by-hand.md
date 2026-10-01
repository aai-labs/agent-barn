# Enter the namespace's capacity limits by hand, and compare them with what the pods commit

Status: Accepted
Date: 2026-10-01
Origin: AF-170

The namespace's ResourceQuota caps the total of every container's limits, and a full quota leaves new agents without a pod and without a clear error. To warn before that happens, a Platform Administrator types the ceilings (memory and CPU) into a dialog on the Platform Resource Usage page, and the page compares them with the limits the namespace's pods have committed, read from kube-state-metrics.

## Considered alternatives

- **Read the quota from the Kubernetes API.** The right source, but the tenant account (`agent-farm-user`) has no `resourcequotas` or `limitranges` rule, and prod answered Forbidden. The deployer cannot create RBAC on the shared cluster, so the grant would have to come from the cluster owners. The cluster health page (AF-266) plans such a grant; if it lands, this decision should be revisited.
- **Put the ceilings in Helm values or an environment variable.** It avoids a table, but an administrator who learns the quota changed would need a deploy to tell the product, and nothing would record who set it.
- **Compare the ceiling with usage, or with the sum of the Agents' own reported limits.** Usage is far below the ceiling long before the quota blocks anything, since the quota counts what containers may use. The Agents' reported limits miss the API, UI and database pods, which the quota counts, and any Agent still on an older healthz script.

## Consequences

- The ceilings can go stale when the cluster owners change the quota. The page shows when they were last changed, each change is a Security Audit Record, and a committed figure above the ceiling is shown as "probably out of date" rather than as a normal reading, since the quota cannot actually be exceeded.
- The committed figure is the sum of `kube_pod_container_resource_limits` over Pending and Running pods, which approximates the quota's own accounting. It needs only the kube-state-metrics the monitoring release already runs under the tenant account, so it adds no permission. If that scrape is off, the figure shows as not available and nothing else breaks.
- The API now stores one thing for this feature: the ceilings. Usage itself is still never stored.
- The ceilings are for the whole namespace, so the Organization filter does not narrow them.

## Revisit when

The platform owners let our account read the ResourceQuota. The page could then show the real quota, and the typed ceilings would become an override or be removed.
