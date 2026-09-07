# AF-282 Organization Template drafts — change log

Status: Completed
Epic: AF-282
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../../adr/2026-09-04-organization-templates-use-draft-publish.md`](../../adr/2026-09-04-organization-templates-use-draft-publish.md), [`../../adr/2026-08-04-platform-template-restores-create-new-versions.md`](../../adr/2026-08-04-platform-template-restores-create-new-versions.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: Organization Templates are draft-gated end to end. `agent_template_draft` / `agent_template_draft_skill` hold one draft per `(organization_id, template_key)`; the draft endpoints create, read, edit, discard and publish it; `GET /{template_key}/lineages` backs the catalogue; version history is per-scope; the side drawer is gone, replaced by `settings/templates/{template_key}` and `settings/templates/new` rendered from the scope-parameterized `ui/src/features/templates/`; and `PATCH /{template_key}` is removed.
- In transition: nothing. `PATCH /{template_key}` now returns 405 and no code path publishes an Organization version outside `POST /{template_key}/draft/publish` and `POST /{template_key}/platform-update`.
- Next: none.
- Blockers: none.

Out of scope by design, and unchanged: `POST /{template_key}/platform-update` still publishes directly, because Platform Templates have no source-update to mirror. Organization-only behavior (forks, lineage deletion, Domain Events, RBAC) kept its existing semantics and only moved from the drawer to the page.

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

### 2026-09-04 — AF-282-07

- Delivered: `PATCH /{template_key}` removed and returning 405; `TemplateService.update_template`, `TemplateRepository.save_template_with_updated_event` and `ui/src/features/agents/hooks/use-update-template.ts` deleted. `save_org_template_version_with_skills` is kept — `update_from_platform` still uses it.
- Changed: the 13 tests covering publish-on-save were relocated onto start-draft -> edit-draft -> publish rather than deleted, so every behaviour they asserted still has coverage; four duplicated by AF-282-03's draft tests were dropped. `rbac-ui` navigates to the editor route instead of the drawer.
- Changed: `templates-and-skills.md` (draft-gated invariant, the four association tables, per-scope version history, draft permissions, an "Author Organization Templates" flow, source map), `CONTEXT.md` (Draft Template Version and Template Restore are no longer platform-only), `docs/INDEX.md` (UI path).
- Decision: Template Update stays as it is. Two earlier proposals — seed-a-draft-and-409, then mirror `SkillService.apply_source_update` — were both rejected as invented behaviour; Platform Templates define no source-update, so there is nothing to bring across.

### 2026-09-04 — AF-282-06

- Delivered: the cutover. `GET /{template_key}/lineages`, `POST ""` returning a draft, `settings/templates/{template_key}` and `settings/templates/new`, the Settings tab rendering the shared panel, and the 940-line side drawer deleted.
- Changed: delete, Apply platform update, the fork banner and the source badges were rebuilt on the published view — deleting the drawer had removed them from the product, which nothing but manual inspection caught.
- Observed: `PlatformTemplateReadSchema` pinned `templateSource: z.literal("pre-defined")`. Once AF-282-05 made that schema serve both scopes it rejected every **custom** Organization template with a response-validation error. Widened to an enum; this was a real defect, not a test artefact.
- Coverage: `settings-templates.spec.ts` rewritten in place, 13 tests; 6 `GET /lineages` integration tests; the create/event tests updated for draft semantics.

### 2026-09-04 — AF-282-05

- Delivered: `ui/src/features/platform-templates/` moved to `ui/src/features/templates/` as a scope-parameterized module — `scope.ts`, scoped hooks, a chrome-free `TemplatesPanel` plus a thin `PlatformTemplatesPage` wrapper, mirroring `ui/src/features/skills/`. All 14 files moved as git renames; no code duplicated.
- Changed: `platform-template-skill-checkbox.tsx` gained a `scope` prop, fixing a live defect — `configuration-draft-editor.tsx` was already feeding it Organization skills while it queried `/api/v1/platform/skills/{id}/versions`, which cannot resolve an org lineage.
- Decision: query keys mirror `skills/utils.ts` exactly — one `templates` base key with the scope folded in as a segment. An earlier split into two base keys was justified as protecting the byte-unchanged platform spec; that reasoning was wrong, since the spec intercepts HTTP and never observes query keys.
- Coverage: `platform-templates.spec.ts` passed byte-unchanged, which is the proof the refactor changed no platform behaviour. It caught one regression on the way: converting the lineage cards from `button` to `Link` changed their ARIA role.

### 2026-09-04 — AF-282-04

- Delivered: `resolve_versions` returns a lineage's own history — the organization's `1..N` sequence once any organization row exists, falling back to the platform lineage otherwise.
- Changed: the Agent re-pin panel now consumes `configuration.sharedVersions`, which the API already returned and the UI had never used, so the active lineage still offers both Platform and Organization rows.
- Observed: the blast radius was one existing test, not the nine the plan predicted. `get_shared_versions` is untouched.

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
- Decision: Organization Templates adopt the Platform Template draft/publish model rather than keeping version-per-save. The draft carries its own fork baseline and version history stops merging Organization and Platform rows. Rationale and consequences are in the ADR. (A first draft of this slice also proposed changing Template Update to seed a draft; that was reverted in AF-282-07 as out of scope, since Platform Templates have no source-update to mirror.)
- Changed: documentation only.
- Follow-up: the context map still routes the Templates UI concern at `../ui/src/features/platform-templates/`. That path is correct until slice 5 creates `../ui/src/features/templates/`, and is repointed in that slice rather than ahead of it.
