# AF-253 Agent Config Tuning — change log

Status: Active
Epic: AF-253
Related context: [`../agents.md`](../agents.md), [`../../adr/2026-08-09-agent-scoped-template-overrides.md`](../../adr/2026-08-09-agent-scoped-template-overrides.md), [`../../../.scratch/af-253-agent-config-tuning/spec.md`](../../../.scratch/af-253-agent-config-tuning/spec.md)

## Current state

- Delivered: full-page Agent configuration, Agent-owned drafts, immutable published Override Versions, authorship, required-Skill validation, and stopped-Agent selection.
- In transition: pending activation state was intentionally discarded; the explicit Apply & Restart workflow remains; Override history and direct source-update workflows remain in later AF-253 slices.
- Next: AF-253-03 — historical selection and rollback.
- Blockers: none for the delivered AF-253-01 slice.

## Changes

### 2026-08-09 — AF-253-01

- Delivered: full-page Agent configuration, private Agent-owned Override drafts, immutable published versions, source metadata, required-Skill validation, optimistic concurrency, and stopped-Agent selection.
- Decision: pending activation state and the dedicated Restart API were discarded; running Agents use the existing explicit Apply & Restart workflow when selecting a published version.
- Follow-up: history/rollback and source updates remain in AF-253-03 and AF-253-04.
