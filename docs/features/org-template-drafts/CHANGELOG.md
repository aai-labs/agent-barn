# AF-282 Organization Template drafts — change log

Status: Active
Epic: AF-282
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../../adr/2026-09-04-organization-templates-use-draft-publish.md`](../../adr/2026-09-04-organization-templates-use-draft-publish.md), [`../../adr/2026-08-04-platform-template-restores-create-new-versions.md`](../../adr/2026-08-04-platform-template-restores-create-new-versions.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: the decision record; the `agent_template_draft` / `agent_template_draft_skill` tables with their cross-domain reference guards; and the Organization draft endpoints (`POST`/`GET`/`PATCH`/`DELETE /{template_key}/draft` and `POST /{template_key}/draft/publish`). The UI does not call them yet.
- In transition: **two ways to publish an Organization version coexist.** `PATCH /{template_key}` still publishes on every save and is what the side drawer uses; the draft endpoints are the replacement and are so far exercised only by tests. `docs/features/templates-and-skills.md` and `CONTEXT.md` still describe the version-per-save contract, which stays accurate until `PATCH` is removed in the final slice. Both write paths produce identical `agent_template` rows and identical fork bookkeeping, so no data written during this window needs migrating.
- Next: narrow `resolve_versions` so a lineage lists only its own versions, then the frontend scope module.
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
| 7 | `PATCH /{template_key}` removed, dead code deleted, documentation resynchronized |

Out of scope, by the rule that Organization Templates adopt only what Platform Templates already define: forks, `POST /{template_key}/platform-update`, lineage deletion, Domain Events, and Organization RBAC all keep their current behavior. They move from the drawer to the page unchanged.

## Changes

### 2026-09-04 — AF-282-03

- Delivered: `POST /{template_key}/draft` (get-or-create, `409` when a draft exists *and* `source_version` is given), `GET`/`PATCH`/`DELETE /{template_key}/draft`, and `POST /{template_key}/draft/publish`. Additive only — `POST ""`, `PATCH /{template_key}` and `platform-update` are untouched, so the side drawer keeps working.
- Changed: `TemplateService` gains `get_org_draft`, `start_org_draft`, `update_org_draft`, `discard_org_draft`, `publish_org_draft`; `TemplateRepository` gains the matching draft accessors plus `publish_org_draft_with_skills`, which fuses the platform `publish_draft_with_skills` with `save_template_with_updated_event` because an Organization publish must write the version, its skills, the draft deletion, and the lifecycle event in one transaction.
- Decision: the fork bookkeeping that lived in `update_template` moves to `start_org_draft` (it describes the source the draft copied), and the audit-field diff moves to `publish_org_draft` (it describes the version being written). Publishing over a `PlatformTemplate` reports `template.updated` with the platform version as `previous_version`, exactly as `PATCH` did; `template.created` is reserved for a lineage with no prior version at all.
- Coverage: 21 integration tests, including the fork pointers a first Organization publish must record, restore-as-new-highest-version, draft invisibility to the three published read endpoints, `template.manage` on writes vs `template.read` on the draft read, org-visible (not global-only) skill resolution, and the three event outcomes.

### 2026-09-04 — AF-282-02

- Delivered: `agent_template_draft` (unique on `(organization_id, template_key)`, carrying its own fork baseline) and `agent_template_draft_skill`, in migration `a2b3c4d5e6f7`. Nothing writes to either table yet.
- Changed: `TemplateRepository._template_key_exists` now also reserves keys held by an organization draft; `purge_org_template_lineage_with_event` deletes the lineage's draft in the same transaction, so a deleted lineage cannot reappear as a draft-only row; `SkillRepository.is_skill_version_referenced_anywhere` and `delete_skill_if_unused` now count organization drafts as references.
- Observed: the two `SkillRepository` clauses are **defense in depth, not the enforcement point** — the `RESTRICT` foreign keys already block both deletes, and endpoint-level tests pass with the clauses removed. They are kept for consistency with the five sibling association tables and for a deterministic blocker instead of the `IntegrityError` fallback. `test_org_template_draft_counts_as_a_skill_version_reference` covers the query clause directly, where no database fallback can mask it.
- Follow-up: the lineage-summary DTOs were deferred to the slice that consumes them rather than landing unused.

### 2026-09-04 — AF-282-01

- Delivered: [`../../adr/2026-09-04-organization-templates-use-draft-publish.md`](../../adr/2026-09-04-organization-templates-use-draft-publish.md), this change log, and the context-map route to it.
- Decision: Organization Templates adopt the Platform Template draft/publish model rather than keeping version-per-save. The draft carries its own fork baseline, Template Update seeds a draft instead of publishing, and version history stops merging Organization and Platform rows. Rationale and consequences are in the ADR.
- Changed: documentation only.
- Follow-up: the context map still routes the Templates UI concern at `../ui/src/features/platform-templates/`. That path is correct until slice 5 creates `../ui/src/features/templates/`, and is repointed in that slice rather than ahead of it.
