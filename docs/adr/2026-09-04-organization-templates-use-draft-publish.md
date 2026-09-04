# Organization Templates use draft/publish

Status: Accepted
Date: 2026-09-04
Origin: AF-282

Organization Template editing published a new immutable `agent_template` version on every `PATCH /organizations/{organization_id}/templates/{template_key}`, so a lineage accumulated a version per save, an edit could not be abandoned, and restoring an older version was impossible without first publishing unreviewed content. Organization Templates now adopt the Platform Template model already proven in `platform_template_draft`: at most one mutable draft per lineage in `agent_template_draft`, unique on `(organization_id, template_key)`, published explicitly into the next immutable `agent_template` version. `PATCH /{template_key}` is removed; content changes are draft-gated, matching the same contract Skills already use in `skill_draft`.

## Considered alternatives

Keeping version-per-save is simpler — no second table, no draft slot to reason about, and no abandoned rows to account for. It was rejected because the junk versions it produces are indistinguishable from deliberate ones in the version picker and in Agent pinning, and because Template Restore has no safe implementation without a draft to stage into.

## Consequences

- **The draft stores its own fork baseline.** `update_template` derived `forked_from_platform_template_id`, `fork_baseline_platform_template_id`, and `fork_baseline_platform_version` from `resolve_latest_template` at write time. With draft/publish there is a window between seeding a draft and publishing it in which a Platform Template publish can land, so the draft records the baseline it actually copied and publish copies it verbatim. This mirrors `AgentTemplateOverrideDraft`, which already stores its source.
- **Restoring an older version can move the baseline backwards.** Restoring Org vN, whose baseline was Platform v1, while the latest Org row's baseline is Platform v2, publishes a version with baseline v1 — so `platform_update_available` reappears. This is the honest answer, because the published content *is* v1's content, and it is consistent with [`2026-08-04-platform-template-restores-create-new-versions.md`](2026-08-04-platform-template-restores-create-new-versions.md).
- **Template Update no longer publishes.** `POST /{template_key}/platform-update` seeds a draft from the newest Platform snapshot for review and returns `409` when a draft already exists, rather than silently discarding in-progress work. A side effect is that this path now emits `template.updated` on publish; it previously emitted no Domain Event, because it was the only writer that bypassed `save_template_with_updated_event`.
- **Version history stops merging scopes.** `resolve_versions` returned Organization and Platform rows merged by version number, with the Organization row shadowing a Platform row at the same number — a premise invalidated when `f6a7b8c9d0e1_normalize_org_fork_versions` gave org forks an independent `1..N` sequence. A lineage with any Organization rows now lists only Organization versions; a never-edited built-in falls back to the Platform lineage. `get_shared_versions`, which deliberately returns both scopes without shadowing for Agent configuration selection, is unchanged.
- **Abandoned drafts are not garbage-collected.** A stale draft only marks its lineage with a `Draft` badge. Tenant deletion cascades from `organization`, and lineage deletion purges the draft. The Platform side has the same property; accepting it keeps both scopes on one model.
- **A draft holds `RESTRICT` references to Skill Versions.** An Organization manager can now be blocked from deleting a Skill by their own unpublished draft.
