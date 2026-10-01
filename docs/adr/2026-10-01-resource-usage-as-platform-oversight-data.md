# Count Agent resource usage as Platform Oversight Data

Status: Accepted
Date: 2026-10-01
Origin: AF-170

Platform Administrators may read CPU and memory of every Agent's container, grouped by Organization and Agent, from a dedicated Platform endpoint. The [oversight ADR](2026-07-30-platform-oversight-without-organization-access.md) says a new oversight field is a classification decision, so this records it: resource usage is a derived reading with no tenant content, and the Platform bears the compute, the same reason it classes cost as oversight data.

## Considered alternatives

- **Keep resource usage Organization-only.** The narrowest boundary, but the Platform pays for the cluster, and its namespace quota is the shared limit all Organizations draw on. Without a cross-Organization view, finding which Organization or Agent is using it, or a container left behind by a deleted Agent, needs `kubectl` or direct Prometheus access.
- **Let a Platform Administrator read the Organization endpoints.** The oversight ADR rejects this for every resource: it recreates cross-tenant authority and makes field-level review hard.
- **Aggregate in Prometheus by the `org_id` and `org_name` labels.** Shorter, but the labels are slugs that are not unique, and the `org_name` one can be wrong. The Platform endpoint instead places every reading by the Agent's Organization in the database and names both from there.

## Consequences

- The Platform read model carries Agent id and name, Organization id and name, memory, CPU, their limits and one throttling ratio. It carries no logs, prompts, configuration, credentials or raw series.
- A reading with no live Agent behind it is kept, as its own row with no Organization, so the Organization rows add up to the platform total and a leaked container is visible.
- Adding another field to this surface, such as per-pod restarts or event text, is a new classification decision, not a consequence of this one.
