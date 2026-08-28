# Unused custom Skill lineages can be deleted

Status: Accepted
Date: 2026-08-27
Origin: AF-186

Custom Platform, Organization, and Agent-private Skill lineages can be hard-deleted when no Agent uses any version of the lineage. The delete removes the lineage's draft, all published versions, and their files. Built-in `aai_cli` lineages remain protected.

## Context

The per-version deletion decision in `2026-08-15-skill-versions-deleted-per-version.md` removed the only cleanup path for a custom Skill lineage. That left a newly created custom Skill with an initial draft and no Agent assignment permanently visible even though it had no consumer. Skill usage is version-specific at assignment time, so the safe deletion question is whether any `AgentSkill` row pins any version of the lineage, not whether the latest version is used.

Skill lineages can also be referenced by Template and Agent Template Override requirements or as the source of a fork. Those references preserve required configuration and provenance and must not be silently invalidated by deleting the source lineage.

## Decision

- Add `DELETE /{skill_id}` to the owning Platform, Organization, and Agent-private Skill routes.
- Allow the operation only for custom lineages and only from the owning scope: Platform Administrators for global custom Platform Skills, Organization managers with `skill.manage` for Organization Skills, and users with Agent `update` access for Agent-private Skills.
- Check every `AgentSkill` row for the lineage, including retained rows for soft-deleted Agents. Any assignment to any version returns `409 Conflict`.
- Check Template/Override requirement rows and fork-source references. Any such reference returns `409 Conflict`; consumers must be detached or the fork/provenance relationship must be handled first.
- Delete the Skill row in the same repository transaction as the reference checks while holding a row lock. Existing database cascades remove only the lineage's own draft, versions, and files. Built-in lineages return `403 Forbidden`.
- Keep per-version deletion unchanged for pruning an individual unreferenced historical version. Its last-version and exact-reference protections still apply.

## Consequences

- Users can clean up unused custom Skills, including a Skill that has only its initial draft.
- A Skill cannot be deleted while any Agent pins any of its versions, even if the pin is historical or retained for a soft-deleted Agent; reassign/remove the pin before deletion.
- Template, Override, and fork-source relationships are preserved rather than implicitly deleted, so deletion may require cleanup in more than one resource.
- Hard deletion is irreversible. The UI exposes the action only for custom lineages in their owning scope, disables it when the current scope reports live Agent usage, and the API remains authoritative for historical or concurrent references.
