# Agent-scoped immutable Template Overrides

Status: Accepted
Date: 2026-08-09
Origin: [AF-253](https://aai-labs.atlassian.net/browse/AF-253), [AF-252](https://aai-labs.atlassian.net/browse/AF-252)

Agent-specific Template customization uses an Agent-owned draft and immutable published snapshots rather than reusing the shared Organization Template lineage. Publishing is separate from selecting a version, and a running Agent applies a selected version only through the explicit Apply & Restart workflow, which stops, selects, and starts it without a pending pin. This preserves sibling isolation, rollback, auditability, and operational safety while retaining the same full-snapshot update model as Organization Templates.

## Considered alternatives

- **Reuse or fork the shared Organization Template row** — rejected because a shared organization version can be referenced by sibling Agents; changing it would violate per-Agent isolation.
- **Mutate the current version in place** — rejected because historical versions would no longer be reliable rollback or audit snapshots.
- **Automatically apply published changes while running** — rejected because template changes should be selected deliberately through an explicit Apply & Restart workflow; no pending selection is needed.
- **Merge or overwrite an existing draft during a source update** — rejected because a user may be actively editing local Override changes. A source update instead selects the complete newer direct shared source version as the Agent's pin, leaving the draft untouched; the user can deliberately discard or publish private work separately.

## Consequences

- The data model needs an Agent-owned Override boundary, immutable version rows, source lineage metadata, author provenance, active selection state, and optimistic-concurrency tokens.
- Publish, selection, and rollback need transactional service/repository seams; running source or historical selection is orchestrated by the UI's explicit Apply & Restart workflow.
- The UI needs a full-page configuration and history experience that distinguishes draft, published, and active states. The existing sidebar/drawer is not the long-term surface.
- Runtime configuration and credentials remain outside Override snapshots. Rollback changes Template behavior only and never rewrites secrets or unrelated Agent settings.
- Version history is retained after soft Agent deletion, so storage and normal-view filtering must account for audit retention.

## Decision update

On 2026-08-11, the pending-selection state and dedicated Restart API were removed as unnecessary complexity with insufficient user value. Running Agents may author and publish overrides safely, while the existing explicit Apply & Restart workflow remains for selecting a version. Direct Platform/Organization source updates repin the Agent to the newer shared source version without mutating an existing Override Draft, preserving in-progress private edits.

## Revisit when

Revisit this decision if Agent Overrides become intentionally shareable, if source updates require three-way merge or automatic rollout, if compliance requires durable Domain Events for every draft/publish/select action, or if runtime configuration must participate in the same rollback boundary.
