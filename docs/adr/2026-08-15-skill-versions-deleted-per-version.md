# Skill versions are deleted per version, not whole lineages

Status: Accepted
Date: 2026-08-15

Whole-lineage skill deletion was removed, and history is pruned one immutable version snapshot at a time instead. A skill lineage is permanent while it exists; only individual published versions can be removed.

## Context

Skills originally offered only whole-lineage deletion (guarded by agent-assignment and latest-template requirements) and treated version history as append-only and immutable. Two problems surfaced:

- Deleting an entire lineage is destructive and irreversible — there is no way to remove one bad snapshot without losing every snapshot and the skill itself.
- The `restored_from_version` provenance marker on `skill_version` (and its mirror `source_version` on `skill_draft`) recorded which older version seeded a restore, but with append-only full snapshots every version is already self-contained; once version deletion is allowed the marker can dangle at a removed snapshot and adds no value.

## Decision

- Remove the whole-lineage `DELETE /{skill_id}` endpoint, the service method, the UI Delete action, and their tests. A lineage cannot be deleted.
- Add `DELETE /{skill_id}/versions/{version}` to remove one immutable version snapshot. Protections: built-ins are never modified (403); the last remaining version is never deletable (409); the currently published (latest) version is deletable only while no non-soft-deleted agent is assigned the skill (409 otherwise), because deleting the latest would silently change what those agents mount on their next restart. Historical versions are always prunable — agents resolve the lineage's latest version, never a specific one.
- `SkillDetailRead` now exposes `is_assigned_to_agent` so the UI can disable deleting the current version while agents use the skill.
- Remove `restored_from_version` from `skill_version` and `source_version` from `skill_draft` (columns, DTOs, UI, and the migration). A restore still seeds the draft from the selected version via the `?source_version=N` query parameter, but the provenance is not persisted on the resulting version.

## Consequences

- Pruning history works without an audit gap for agents or templates: agents mount the exact version they pin, and templates reference the lineage.
- Cleaning up a bad published version requires publishing a fixed one, re-pinning affected agents, then deleting the bad version — a version pinned by any agent is protected from deletion.
- Version history is no longer strictly append-only; snapshots remain immutable once published, but the collection can shrink.
- The migration drops two columns; any tooling reading `restored_from_version`/`source_version` must stop.
