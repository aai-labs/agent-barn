# Predefined templates are global platform resources

Status: Accepted
Date: 2026-07-28
Origin: AF-236 (platform refactor)

Predefined templates were per-Organization rows cloned by a seeder on every org creation/signup. To match the platform model already used by built-in aai-cli skills, predefined templates are now global platform resources (`organization_id IS NULL`) seeded once at startup, and an organization sees global predefined templates plus its own custom templates through a scope-aware repository filter (`organization_id = org_id OR organization_id IS NULL`).

## Decision

- `agent_template.organization_id` is nullable. Global predefined rows have `organization_id IS NULL`; custom rows are org-scoped.
- Uniqueness is split into two partial unique indexes: `(template_slug, version) WHERE organization_id IS NULL` for the global catalogue and `(organization_id, template_slug, version) WHERE organization_id IS NOT NULL` for custom templates. A single UNIQUE constraint cannot express both with a NULLable org_id.
- The agent's org-scoped composite FK to `agent_template` is dropped. A global predefined row can never satisfy an agent-scoped FK, so template existence is enforced at the service boundary (create/update/re-pin return 404 for unknown pins), mirroring agent-skill integrity.
- Editing a predefined lineage in an org produces an org-scoped version > 1 alongside the global v1. The seeder only ever refreshes the global v1 in place; org customizations are never clobbered.
- The seeder no longer takes an `organization_id`; it runs once in the application lifespan. Organization creation and signup no longer seed a per-org catalog.

## Consequences

- A new organization immediately sees the predefined catalogue with no seeding step.
- Agents carry `(template_slug, template_version)` pin columns without a database FK; a bug that pins a non-existent template is caught by the service 404, not by a constraint violation.
- Skill-deletion guards consider both global predefined and org-scoped templates when deciding whether a skill is still required.
- Reverting requires re-scoping each global predefined v1 row to a single owning org (the data migration is not trivially reversible when multiple orgs pin the same predefined lineage).

Current behavior and source paths are documented in [`../features/templates-and-skills.md`](../features/templates-and-skills.md).
