# AF-253 Agent Config Tuning — change log

Status: Active
Epic: AF-253
Related context: [`../agents.md`](../agents.md), [`../../adr/2026-08-09-agent-scoped-template-overrides.md`](../../adr/2026-08-09-agent-scoped-template-overrides.md), [`../../../.scratch/af-253-agent-config-tuning/spec.md`](../../../.scratch/af-253-agent-config-tuning/spec.md)

## Current state

- Delivered: full-page Agent configuration, Agent-owned drafts, immutable published Override Versions, authorship, required-Skill validation, shared and Override history, safe historical selection/rollback, draft preservation, and retention after soft Agent deletion.
- In transition: pending activation state was intentionally discarded; the explicit Apply & Restart workflow remains; direct source-update workflows remain in a later AF-253 slice.
- Next: AF-253-04 — direct source updates.
- Blockers: none for the delivered AF-253-01 and AF-253-03 slices.

## Changes

### 2026-08-11 — AF-253-03

- Delivered: the existing configuration history and selection flow satisfies historical selection and rollback without a compensating version; independent drafts remain untouched, shared switching preserves Override history, and soft-deleted Agents retain hidden history.
- Decision: rollback is selecting an existing immutable published Override Version; no separate rollback endpoint, migration, or pending pin is needed.
- Follow-up: direct Platform/Organization source updates remain in AF-253-04.

### 2026-08-09 — AF-253-01

- Delivered: full-page Agent configuration, private Agent-owned Override drafts, immutable published versions, source metadata, required-Skill validation, optimistic concurrency, and stopped-Agent selection.
- Decision: pending activation state and the dedicated Restart API were discarded; running Agents use the existing explicit Apply & Restart workflow when selecting a published version.
- Follow-up: history/rollback and source updates remain in AF-253-03 and AF-253-04.
