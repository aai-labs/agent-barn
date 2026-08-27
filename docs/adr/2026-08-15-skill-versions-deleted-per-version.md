# Skill versions are deleted per version, not whole lineages

Status: Superseded by `2026-08-27-delete-unused-custom-skill-lineages.md`
Date: 2026-08-15

At the time of this decision, whole-lineage skill deletion was removed and history was pruned one immutable version snapshot at a time. The superseding ADR restores whole-lineage deletion for unused custom lineages while retaining the per-version protections below.

## Context

Skills originally offered only whole-lineage deletion (guarded by agent-assignment and latest-template requirements) and treated version history as append-only and immutable. Two problems surfaced:

- Deleting an entire lineage is destructive and irreversible — there is no way to remove one bad snapshot without losing every snapshot and the skill itself.
- The `restored_from_version` provenance marker on `skill_version` (and its mirror `source_version` on `skill_draft`) recorded which older version seeded a restore, but with append-only full snapshots every version is already self-contained; once version deletion is allowed the marker can dangle at a removed snapshot and adds no value.

## Decision

- Remove the whole-lineage `DELETE /{skill_id}` endpoint, the service method, the UI Delete action, and their tests. A lineage cannot be deleted.
- Add scoped `DELETE /{skill_id}/versions/{version}` operations to remove one immutable version snapshot. Organization and Agent routes can only mutate versions owned by that scope; Platform Administrators manage Platform Skill versions. The last remaining version is never deletable (409), and a version referenced by an Agent pin, Template/Override requirement, draft, or fork source is never deletable (409). Historical versions with no references are prunable because runtimes mount exact pinned snapshots.
- `SkillVersionRead` exposes `is_pinned_by_agent` so the UI can disable the Delete button on a per-version basis and show a "Pinned by agent" badge.
- Remove `restored_from_version` from `skill_version` and `source_version` from `skill_draft` (columns, DTOs, UI, and the migration). Restore-as-draft is removed entirely; recovering from a bad version is a per-agent concern handled by re-pinning the agent's assigned skill version.

## Consequences

- Pruning history works without an audit gap for agents or templates: agents mount the exact version they pin, and templates reference the lineage.
- Cleaning up a bad published version requires publishing a fixed one, re-pinning affected Agents and updating any Template/Override references, then deleting the bad version — referenced snapshots are protected from deletion.
- Version history is no longer strictly append-only; snapshots remain immutable once published, but the collection can shrink.
- Platform, Organization, and Agent Skill scopes now share the same immutable-version contract. Fork source provenance is stored as an explicit `(source_skill_id, source_skill_version)` reference, and any tooling reading the removed legacy restore fields must stop.
