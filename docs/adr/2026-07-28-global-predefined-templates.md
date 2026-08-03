# Predefined templates are global platform resources

Status: Accepted
Date: 2026-07-28
Origin: AF-236 (platform refactor)

Predefined templates were per-Organization rows cloned by a seeder on every org creation/signup. They are now global platform resources in a dedicated `platform_template` table (no `organization_id`), mirroring the built-in skill model with real referential integrity. `agent_template` is strictly organization-scoped again (custom templates + org forks). Agents pin a template version via one of two mutually-exclusive FKs.

## Decision

- `platform_template` is a global table with uniqueness on `(template_slug, version)`. `platform_template_skill` holds its required-skill associations. No `organization_id`.
- `agent_template` is strictly organization-scoped (`organization_id` NOT NULL, unique on `(organization_id, template_slug, version)`). It holds custom templates and org forks of predefined templates. `forked_from_platform_template_id` (nullable FK → `platform_template.id`) records fork lineage so "update available" detection is possible later.
- Agents pin a template via exactly one of `platform_template_id` or `agent_template_id` (both nullable FKs with `ON DELETE RESTRICT`), enforced by a CHECK constraint `(platform_template_id IS NULL) <> (agent_template_id IS NULL)`. This restores DB-level referential integrity that the earlier nullable-org_id approach could not provide.
- The predefined seeder writes to `platform_template` at startup. Organization creation and signup no longer seed templates.
- Editing a platform predefined template forks it: the PATCH creates an `agent_template` row at `version = platform_v + 1` with `forked_from_platform_template_id` set. The seeder only ever refreshes the platform v1 in place; org forks are never clobbered.
- Template listing/version-history resolves across both tables (org first, then platform), so an org sees global predefined templates plus its own custom templates and forks. An org fork at a higher version shadows the platform v1 as the lineage's latest.

## Consequences

- A new organization immediately sees the predefined catalogue with no seeding step.
- Agents carry real FKs to their pinned template — no service-layer existence check needed for pin integrity.
- An earlier approach used a nullable `organization_id` on `agent_template` (NULL = global). That overloaded a FK column and dropped the agent composite FK. This revision replaces it with a dedicated `platform_template` table and two mutually-exclusive FKs, restoring clean boundaries and referential integrity.
- Skill-deletion guards check both `agent_template_skill` and `platform_template_skill` when deciding whether a skill is still required.

Current behavior and source paths are documented in [`../features/templates-and-skills.md`](../features/templates-and-skills.md).
