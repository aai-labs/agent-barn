# Platform Template seeding becomes a one-time file-based bootstrap

Status: Accepted
Date: 2026-08-03
Origin: AF-183 (Agent tuning UI: skills, config overrides)

Platform Templates are currently authored as Python (`api/domains/templates/predefined/*.py`, e.g. `code_reviewer.py`, `scrum_master.py`) and the seeder refreshes platform v1 of each lineage in place on every startup. AF-183 gives Platform Administrators a draft/publish UI to author Platform Templates directly in the database. A code seeder that keeps refreshing v1 on every deploy would silently clobber whatever an admin has published through that UI, so the two authoring paths can't coexist as they're shaped today.

## Decision

- The Python-defined predefined templates are replaced by a structured directory of Markdown files (one per template artifact: soul, identity, user, tools, agents, boot, bootstrap, heartbeat) plus an optional YAML settings file per template for non-content metadata (display name, description, required skills); the directory name supplies the stable template key.
- The seeder reads this directory and writes `platform_template` rows only as a **one-time bootstrap** — it seeds a lineage's v1 if that lineage doesn't already exist in the database, and never overwrites an existing row on subsequent startups.
- Once a lineage exists in the database, the code/file directory stops being its source of truth. All further versions are authored and published through the admin Draft Template Version UI.

## Consequences

- New environments (fresh deploys, local dev) still get the built-in catalogue seeded automatically with no manual setup.
- Admin-published changes to a Platform Template are permanent and survive redeploys — the seeder can no longer stomp them.
- The Markdown+YAML directory becomes dead weight for any lineage once it has been published through the admin UI at least once; it only matters for bootstrapping brand-new environments or brand-new lineages.
- Restoring or resetting a lineage to its "factory" file-based definition is no longer possible through a redeploy; it would require an explicit admin action (e.g. a new draft authored to match the files).

Domain terms — Draft Template Version, Fork Baseline Version, Template Update — are documented in [`../../CONTEXT.md`](../../CONTEXT.md).
