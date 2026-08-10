# Agent-scoped immutable Template Overrides

Status: Accepted
Date: 2026-08-09
Origin: [AF-253](https://aai-labs.atlassian.net/browse/AF-253), [AF-252](https://aai-labs.atlassian.net/browse/AF-252)

Agent-specific Template customization uses an Agent-owned draft and immutable published snapshots rather than reusing the shared Organization Template lineage. Publishing is separate from selecting a version, and a running Agent applies a selected version only through an explicit Restart. This preserves sibling isolation, rollback, auditability, and operational safety while retaining the same full-snapshot update model as Organization Templates.

## Considered alternatives

- **Reuse or fork the shared Organization Template row** — rejected because a shared organization version can be referenced by sibling Agents; changing it would violate per-Agent isolation.
- **Mutate the current version in place** — rejected because historical versions would no longer be reliable rollback or audit snapshots.
- **Automatically apply published changes on the next Start or while running** — rejected because an ordinary Stop followed by Start must remain a safe recovery path that uses the known active pin; applying a pending choice requires explicit Restart.
- **Merge source updates with local Override changes** — rejected in favor of copying the complete source snapshot, matching Organization Template Updates and keeping the result deterministic. Local changes are intentionally replaced, while prior Override Versions remain available.

## Consequences

- The data model needs an Agent-owned Override boundary, immutable version rows, source lineage metadata, author provenance, active/pending selection state, and optimistic-concurrency tokens.
- Publish, selection, and rollback need transactional service/repository seams; runtime startup failure must leave the selected version active and the Agent in `ERROR` rather than silently reverting the snapshot.
- The UI needs a full-page configuration and history experience that distinguishes draft, published, active, and pending states. The existing sidebar/drawer is not the long-term surface.
- Runtime configuration and credentials remain outside Override snapshots. Rollback changes Template behavior only and never rewrites secrets or unrelated Agent settings.
- Version history is retained after soft Agent deletion, so storage and normal-view filtering must account for audit retention.

## Revisit when

Revisit this decision if Agent Overrides become intentionally shareable, if source updates require three-way merge or automatic rollout, if compliance requires durable Domain Events for every draft/publish/select action, or if runtime configuration must participate in the same rollback boundary.
