# AF-282 Organization Template drafts — change log

Status: Active
Epic: AF-282
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../../adr/2026-09-04-organization-templates-use-draft-publish.md`](../../adr/2026-09-04-organization-templates-use-draft-publish.md), [`../../adr/2026-08-04-platform-template-restores-create-new-versions.md`](../../adr/2026-08-04-platform-template-restores-create-new-versions.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: the accepted decision record only. No behavior has changed; Organization Template editing still publishes a version per `PATCH /{template_key}` and still runs in the Settings side drawer.
- In transition: nothing yet. `docs/features/templates-and-skills.md` and `CONTEXT.md` still describe the version-per-save contract, which remains accurate until the endpoint is removed; both are rewritten in the final slice.
- Next: the `agent_template_draft` and `agent_template_draft_skill` tables, their migration, and the cross-domain reference guards that must move with them.
- Blockers: none.

## Slice plan

Each slice is independently deployable. The draft endpoints land additively before anything is removed, so the drawer keeps working until the UI is cut over.

| Slice | Scope |
| ----- | ----- |
| 1 | Decision record, epic log, context map |
| 2 | Draft tables, migration, key-allocation and Skill-reference guards |
| 3 | Organization draft endpoints (additive; `PATCH /{template_key}` untouched) |
| 4 | `resolve_versions` stops merging Organization and Platform history |
| 5 | Scope-parameterized `ui/src/features/templates/` (refactor, no behavior change) |
| 6 | Organization Templates panel and editor routes; side drawer deleted |
| 7 | Template Update seeds a draft instead of publishing |
| 8 | `PATCH /{template_key}` removed, dead code deleted, documentation resynchronized |

## Changes

### 2026-09-04 — AF-282-01

- Delivered: [`../../adr/2026-09-04-organization-templates-use-draft-publish.md`](../../adr/2026-09-04-organization-templates-use-draft-publish.md), this change log, and the context-map route to it.
- Decision: Organization Templates adopt the Platform Template draft/publish model rather than keeping version-per-save. The draft carries its own fork baseline, Template Update seeds a draft instead of publishing, and version history stops merging Organization and Platform rows. Rationale and consequences are in the ADR.
- Changed: documentation only.
- Follow-up: the context map still routes the Templates UI concern at `../ui/src/features/platform-templates/`. That path is correct until slice 5 creates `../ui/src/features/templates/`, and is repointed in that slice rather than ahead of it.
