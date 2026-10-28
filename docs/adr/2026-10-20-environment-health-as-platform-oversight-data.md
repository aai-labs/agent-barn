# Count the namespace's health as Platform Oversight Data, with no cluster text

Status: Proposed
Date: 2026-10-20
Origin: AF-266

Platform Administrators may read the health of the namespace the platform runs in — its own services, the Agents' pods and volume claims, the quota against them, firing alerts and recent Warning Events — from a dedicated, read-only Platform endpoint. A staging incident made the case: a new Agent failed because the storage quota was full (30Gi of 30Gi), and the only place that said so was the error on the failed Agent, while the API and every pod looked healthy. The [oversight ADR](2026-07-30-platform-oversight-without-organization-access.md) says a new oversight field is a classification decision, and the [resource usage ADR](2026-10-01-resource-usage-as-platform-oversight-data.md) names per-pod restarts and event text as needing one, so this records it.

## Considered alternatives

- **Leave it to `kubectl` and Grafana.** The bastion and direct cluster access are what the ticket set out to remove: diagnosing a full quota needed both, and the Agent's owner, who sees the failure first, has neither.
- **Show the cluster's own text.** Event messages and container messages are the most direct explanation, but they can name Secrets, quote mount paths and echo request bodies, which the provisioning-failure contract already refuses to forward. The page gets fixed explanations instead, and the one message shape whose parts can be validated — a quota or LimitRange rejection — is rebuilt from those parts.
- **A second page per Organization.** The namespace and its quota are shared by every Organization, so a per-Organization view could not answer "why can no Agent start".

## Consequences

- The read model carries: the namespace name; names of Deployments, StatefulSets, pods and volume claims, which this platform or its charts generate; replica counts, readiness, phases and restart counts; waiting and termination reasons from a fixed list; quota lines by their standard resource names (`requests.storage`, `pods`, ...) with used and hard figures; Warning Event reasons, counts and times, with the object's kind and name only for a fixed list of kinds; the name and severity of a firing alert from the monitoring chart's own rules; and, for an Agent in ERROR, its stored failure rebuilt through `persisted_provisioning_error`, detail included.
- It carries no log text, Event or container messages, alert annotations, labels other than the ones listed, quota names (the cluster's owners choose those), Secret or ConfigMap names or contents, or credentials.
- A failed Agent's detail is shown here, where the Platform Resource Usage row leaves it out. The detail's grammar admits only quota lines and quantities, a LimitRange bound, a denied verb and resource kind, or a fixed exception name, and it is the part an administrator acts on ("requests.storage: requested 1Gi, used 30Gi, limit 30Gi").
- A resource is linked to an Agent only through the id in a label this platform sets (`app`, `agentbarn.io/agent-id`), and the Agent and its Organization are named from the database. The `org-id`, `agent_name` and `org_name` labels are never used, so a wrong label cannot move an Agent into another Organization. A claim or pod whose id has no live Agent is shown as orphaned, with only the id.
- The page is read-only. Deleting an orphaned claim or restarting a workload is a separate decision with its own audit trail.
- Each source is optional. A read the service account is refused (403) is shown as "not permitted", an outage as "unavailable", and the rest of the page still renders, so the page works with today's tenant grant and improves without a code change when the cluster's owners grant `resourcequotas` or `events`.
- Adding a field to this surface, such as Event messages or log lines, is a new classification decision, not a consequence of this one.
