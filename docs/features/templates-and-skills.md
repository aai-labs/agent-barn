# Templates and Skills

## Read when

Read before changing template versioning, predefined template seeding, template Markdown fields, Agent Template Overrides, required skills, skill versioning, skill file storage, skill provider requirements, or agent skill mounting.

## Role in the system

Templates provide versioned agent configuration; Skills provide packaged instructions and references. A template version can require skills, while each agent pins a template version and carries its own explicit skill assignments. Built-in catalogue content is a platform/global resource rather than belonging to a customer Organization.

## Template invariants

- Every template lineage has an immutable `template_key`. New custom and Platform Template lineages receive a server-generated opaque key in the `tpl-<12 lowercase hex>` format; the display `template_name` is not unique. Existing key values are preserved during the slug-to-key migration, and persisted Agent pins remain attached to the same template rows.
- Predefined templates are global platform resources in the `platform_template` table (no `organization_id`), seeded once at startup. Custom templates and org forks of predefined templates are organization-scoped in `agent_template` (`organization_id` NOT NULL).
- `platform_template` uniqueness is `(template_key, version)`. `agent_template` uniqueness is `(organization_id, template_key, version)`.
- Template visibility is unified: an organization sees global `platform_template` rows plus its own `agent_template` rows. Repository resolution checks the organization's lineage first, so an org fork shadows the platform lineage until the organization explicitly applies a Template Update.
- Agents pin an exact template version via one of two mutually-exclusive FKs: `platform_template_id` (global predefined) or `agent_template_id` (org-scoped custom/fork). A CHECK constraint ensures exactly one is set, restoring DB-level referential integrity. Publishing a later version does not move existing agents.
- Creating a custom template starts at version 1. Updating a custom template inserts the next org-scoped version, preserves omitted content, and preserves required skills unless replacements are supplied. Template saves and publishes do not block on `in_use`; live-agent references only block lineage deletion.
- Editing a platform predefined template creates the first organization snapshot at **Org v1**, regardless of the platform version. The row stores the original platform source ID, the current platform baseline ID, and the denormalized baseline version. Later organization edits publish Org v2, v3, and so on. Organization Template reads expose the lineage-level `platform_update_available` result of comparing the latest organization version's baseline with the latest published platform version; the same result is used across version history so selecting an older version cannot change update availability. The Org Template UI labels the row as an Organization fork rather than a Built-in template. The seeder only bootstraps missing platform lineages; org forks are never clobbered.
- Template name, key, and source remain stable across versions. Template content consists of the configured Markdown artifacts: soul, identity, user, tools, agents, boot, bootstrap, and heartbeat.
- Required-skill associations are stored in `agent_template_skill` (org-scoped) and `platform_template_skill` (global), mirroring the template split.
- AF-253 Agent Template Overrides are Agent-scoped snapshots, not Organization Template rows. They copy the complete source version—including metadata, all eight Markdown artifacts, and required-skill requirements—into an Agent-owned draft/version lineage when a draft is created. A later direct source update repins the Agent to the newer shared Platform or Organization version without mutating an existing Override Draft; the accepted draft/publish/select/restart contract is documented in the AF-253 feature changelog.
- Each required-skill row carries a nullable `group_key`. `NULL` means the skill is standalone and AND-required (must be assigned). Rows sharing a non-`NULL` `group_key` on the same template form an "at least one of" group: at hire/update time at least one member must be assigned, and an agent can never be updated down to zero assigned members in a group it once had one in. A skill cannot be both standalone and a group member on the same template version (enforced at the API layer). `TemplateCreate`/`TemplateUpdate` accept groups via `required_skill_groups` (list of `{group_key, skill_ids}`) alongside the existing `required_skill_ids` for standalone skills.

## Skill invariants

- Built-in `aai_cli` skills are global Platform Resources; custom skills belong to one organization.
- Built-in skills cannot be updated or deleted through normal skill CRUD.
- A Skill row is a *lineage*: stable identity, name, slug, and mount location. Content lives in append-only `skill_version` rows, each owning a flat set of `skill_file` rows. The published version is always the lineage's highest `version`, so "latest" and "current" coincide and no current-version pointer exists. Rollback publishes a *new* version copied from an older one; history is never mutated.
- `GET /{skill_id}/versions` lists a lineage's version history (newest first); `GET /{skill_id}/versions/{version}` returns one version's files. `POST /{skill_id}/versions/{version}/restore` publishes a new version copied from an older one's content and records `restored_from_version`, requires `skill.manage`, and is rejected for built-ins the same way other content changes are.
- Agents and templates reference a skill *lineage*, never a version. `TemplateRequiredSkillRead` therefore carries no version, while the Skills UI reads `SkillSummaryRead`/`SkillDetailRead`, which do.
- Skill files are text, addressed by a path relative to the skill root. Directories are implied by the path and never stored. Paths are validated for traversal, absolute paths, archive metadata, disallowed characters, case-insensitive duplicates, and per-file/total size caps (`api/domains/skills/files.py`).
- `root_dir` is the workspace directory a skill's files are written to, and is *not* derived from the slug at mount time. Custom skills use their slug; all ten built-ins deliberately share `aai-cli` so their published pointer paths (`./skills/aai-cli/jira_skill.md`) keep resolving. Renaming a skill never moves its files.
- Two skills sharing a `root_dir` can claim the same workspace path. The manifest builder applies skills in a stable order (by name), first claim wins, and losing claims are returned as collisions and logged against the agent at start.
- `tools_pointer` is a curated override carried only by built-ins. For every other skill the pointer is derived from name, description, and entry path, so a rename or description edit cannot leave a stale pointer behind.
- A custom skill cannot be deleted while assigned to an agent or required by a latest template version.
- Template-required skills must be explicitly present on the agent: standalone (ungrouped) required skills must all be present; for a required-skill group, at least one member must be present. A group member only becomes individually "required" (cannot be removed) once it is the agent's sole assigned member of that group.
- Agent create/update validates assigned-skill provider requirements against Agent Secrets. Editing a skill's required providers does not revalidate existing agent assignments, and start does not repeat that validation.
- At start time, eligible built-in provider skills are mounted implicitly when their provider credential exists. This does not create an explicit agent-skill assignment.

## Authorization invariants

- Template list, detail, and version-history APIs require the Organization Permission `template.read`; create and version-publishing APIs require `template.manage`.
- Skill list and detail APIs require the Organization Permission `skill.read`; custom Skill create, update, and delete APIs require `skill.manage`.
- The fixed Organization Member Role can read and use Organization Templates and Skills but cannot mutate their shared definitions. The UI preserves read-only drawers for Members and hides create/edit/delete controls; Organization Owner/Admin receive management authority.
- Permission checks remain at user-facing service boundaries. Internal Agent workflows may resolve visible Templates and Skills directly after enforcing the Agent action Permission, so Member Agent creation and configuration do not require shared-definition management authority.

## Relationships and boundaries

Template services own lineage/version behavior and user-facing Permission enforcement. Skill services own archive, deletion safety, and user-facing Permission enforcement. Agent services enforce the combined assignment contract during create, update, and repin, then materialize skills at start. Association tables currently live in the Agents domain, so changes to template-skill or agent-skill relationships cross all three domains.

## Primary flows

### Publish a template version

Validate referenced skills, create the next immutable custom version, copy omitted fields and retained requirements, then expose it as the latest lineage version. Existing agent pins remain unchanged.

### Apply a Template Update

For an organization fork with a newer Platform Template Version available, an explicit Template Update clones the complete newer platform snapshot—including content and required skills—into the next organization version. Organization customizations are intentionally replaced by the platform snapshot. The original fork origin remains intact, the stored platform baseline ID/version advances to the adopted platform version, and existing Agent pins remain unchanged.

### Apply a source update to an Agent Override

An Agent Override may show an update only from the direct Platform or Organization lineage of its Override Source Version. The user explicitly selects the complete newer source snapshot as the Agent's shared pin; a stopped Agent changes pins immediately and a running Agent uses Apply & Restart. Source updates never mutate or merge local Override Draft edits, never publish an Override Version, and an unavailable source does not invalidate an existing self-contained Override snapshot.

### Assign and mount skills

Explicit assignments are persisted after organization access and provider requirements pass. Agent start loads those skills, adds eligible built-in provider skills, loads each skill's latest-version files, builds the runtime skill manifest (prefixing every path with the skill's `root_dir` and reporting collisions), and appends skill pointers to rendered tool context.

### Author Platform Templates

Platform Administrators use the Platform View's Platform Templates catalog (`/dashboard/platform/templates`) to manage one draft at a time for each global template lineage. Each lineage opens in its dedicated detail page (`/dashboard/platform/templates/{template_key}`), which can switch between every published version and show that version's metadata, Markdown artifacts, and required skills read-only. `Start draft` or `Continue editing draft` enters the draft editor. Selecting an older published version offers a Template Restore, which seeds the draft from that historical version; publishing creates the next immutable version rather than mutating history. New lineages start at `/dashboard/platform/templates/new`. The editor changes the template metadata, all eight Markdown prompt artifacts, and global required-skill selections. It never asks the author to supply or derive the template key. Saving keeps the draft unpublished; publishing creates the next immutable `platform_template` version and clears the draft. Existing organization and Agent pins remain unchanged until an organization explicitly applies a Template Update or repins an Agent.

## Source map

| Concern                             | Authoritative source                                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Template model and DTOs             | `../../api/domains/templates/models.py`                                                                                         |
| Template versioning and seeding     | `../../api/domains/templates/service.py`, `../../api/domains/templates/predefined/`                                                                         |
| Template persistence                | `../../api/domains/templates/repository.py`                                                                                     |
| Skill model and DTOs                | `../../api/domains/skills/models.py`                                                                                            |
| Skill file path rules               | `../../api/domains/skills/files.py`                                                                                             |
| Skill versioning and CRUD rules     | `../../api/domains/skills/service.py`, `../../api/domains/skills/repository.py`                                                       |
| Skill manifest and collision check  | `../../api/domains/agents/aai_cli_skills/__init__.py`                                                                           |
| Built-in skill seeding              | `../../api/domains/skills/skill_seeder.py`, `../../api/domains/agents/aai_cli_skills/`                                                |
| Assignment enforcement and mounting | `../../api/domains/agents/service.py`                                                                                           |
| UI template surface                 | `../../ui/src/features/agents/components/templates-panel.tsx`, `../../ui/src/features/platform-templates/`                     |
| UI skill surface                    | `../../ui/src/features/skills/`                                                                                                 |
| Tests                               | `../../api/tests/integration/test_templates.py`, `../../api/tests/integration/test_skills.py`, `../../api/tests/integration/test_agents.py` |

## Change impact

Template changes affect agent pinning/rendering, predefined seeds, required skills, UI template schemas, and existing-version behavior. Changes to predefined v1 requirements must account for already-pinned agents. Agent Template Override changes additionally affect Agent-owned snapshot persistence, source update discovery, pin selection, restart activation, rollback, and sibling isolation. Skill changes affect file path validation, version publishing, assignment/deletion guards, agent start manifests, provider requirements, templates, and the Skills UI; provider-requirement edits must account for existing assignments. Deletion cascades version and file rows while the lineage-level guards stay in place. Verify all three domain test suites when their relationship changes.

Required-skill *group* changes (the `group_key` column and the "at least one of" model) affect: agent create/update validation (group membership, the never-drop-to-zero grandfathering rule), predefined seeding idempotency (a group's seeded membership can be a subset when not all member skills exist yet), the hire dialog (multi-select group UI, gates Hire until a choice is made), the template editor (group authoring: create/add/remove member/dissolve), and the canonical Agent configuration page's Template selection flow (group choice re-derived against the new template's groups). Changes here must be verified against both `agent_template_skill` and `platform_template_skill` groups.
