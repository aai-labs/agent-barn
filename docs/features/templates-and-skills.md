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

- Skills have three additive scopes: Platform (`organization_id IS NULL`, `agent_id IS NULL`), Organization (`organization_id` set, `agent_id IS NULL`), and Agent (`organization_id` and `agent_id` set). An Agent can see Platform Skills, its Organization's Skills, and its own private Skills; another Agent's private Skills are never visible.
- Platform Skills are global resources. The checked-in aai-cli bundle mirrors [`aai-cli/bundled/skills`](https://github.com/aai-labs/aai-cli/tree/main/bundled/skills): each `aai-<integration>/` directory contains exactly one root `SKILL.md` plus optional reference files. `api/domains/agents/aai_cli_skills/bundled/skills/` is the bootstrap source; the database is canonical after seeding.
- A Skill row is a lineage: stable identity, display name, immutable slug, scope, and mount directory. Content lives in `skill_version` rows, each owning a flat set of UTF-8 `skill_file` rows. Every published version contains exactly one root `SKILL.md`; all other paths are relative to that Skill root. ZIP bytes are migration input only and are not steady-state storage.
- Every lineage has at most one mutable `skill_draft`. New Skills and forks start with a draft and no published version. Publishing copies the draft into the next immutable version, applies staged description/provider metadata, and clears the draft. `PATCH /{skill_id}` only renames an owned lineage; content and metadata changes are draft-gated.
- Platform administrators can create, edit, publish, rename, and delete unused custom Platform Skill lineages. Organization managers can create, edit, publish, rename, and delete unused custom lineages or individual versions only for Organization-owned Skills; Platform Skills are visible read-only to Organizations and can be forked. Agent owners can perform the same lifecycle operations for Agent-private Skills through the Agent-scoped routes.
- `GET /{skill_id}/versions` lists a lineage's history newest-first; `GET /{skill_id}/versions/{version}` returns one immutable snapshot and its files. A version cannot be deleted if it is the last version, pinned by an Agent, required by any Template/Override, or referenced as a fork source.
- `DELETE /{skill_id}` hard-deletes a custom Skill lineage together with its draft, versions, and files when no `AgentSkill` row pins any version and no Template, Override, or fork-source row references the lineage. Built-in `aai_cli` lineages cannot be deleted; these external references must be removed before lineage deletion. The operation is available only in the lineage's owning scope.
- Forks are independent lineages. An Organization or Agent fork records the exact source `(skill_id, skill_version)` on its draft/version. If no draft exists, Apply Update copies the newest direct source and publishes immediately; if a draft exists, Apply Update replaces its files and metadata and leaves it unpublished. Existing consumers never repin automatically. Direct consumers explicitly select a newer published version.
- Agents and Templates pin immutable Skill Versions. Template and Override association rows store `(skill_id, skill_version)`; Agent assignments store `agent_skill.pinned_version`. Publishing never moves an existing pin. `AgentCreate`/`AgentUpdate` accept optional `skill_versions`; omitted assignments pin the latest version at apply time.
- Skill files are UTF-8 text. Paths are validated for traversal, absolute paths, archive metadata, disallowed characters, case-insensitive duplicates, and per-file/total size caps (`api/domains/skills/files.py`). Legacy custom entry paths migrate deterministically to `SKILL.md`; missing or ambiguous Markdown candidates abort with repair guidance.
- Runtime materialization prefixes files with each Skill's isolated slug directory. Hermes writes them beneath `/workspace/skills`; OpenClaw writes them beneath `/home/node/.openclaw/workspace/skills`. The manifest includes the exact Agent-pinned version and reports path collisions instead of silently overwriting content.
- `tools_pointer` is a curated Platform/aai-cli pointer or a derived pointer for custom Skills. It always references `./skills/<skill-root>/SKILL.md`, so renaming a lineage never moves its files or invalidates its entry path.
- Agent create/update validates declared `required_providers` against Agent Secrets. Skills never grant permissions, tools, or secrets; provider requirements are declarative integration metadata. Eligible aai-cli Skills with a supported configured provider may still be auto-mounted, but that does not create an explicit assignment.
- Template-required skills must be explicitly present on the Agent: standalone required skills must all be present; for a required-skill group, at least one member must be present. A group member becomes individually required only when it is the sole assigned member of that group.

## Authorization invariants

- Template list, detail, and version-history APIs require the Organization Permission `template.read`; create and version-publishing APIs require `template.manage`.
- Organization Skill list and detail APIs require the Organization Permission `skill.read`; Organization Skill create, update, draft, publish, source-update, fork, version deletion, and unused-lineage deletion require `skill.manage`. Platform Skill APIs require Platform Administrator authority. Agent-private Skill APIs require the corresponding Agent Access Permission and never expose another Agent's private lineages; private-lineage deletion requires Agent update access.
- The fixed Organization Member Role can read and use Organization Templates and Skills but cannot mutate their shared definitions. The UI preserves read-only drawers for Members and hides create/edit/delete controls; Organization Owner/Admin receive management authority.
- Permission checks remain at user-facing service boundaries. Internal Agent workflows may resolve visible Templates and Skills directly after enforcing the Agent action Permission, so Member Agent creation and configuration do not require shared-definition management authority.

## Relationships and boundaries

Template services own lineage/version behavior and user-facing Permission enforcement. Skill services own file validation, version/draft/source-update behavior, deletion safety, and user-facing Permission enforcement. Agent services enforce the combined assignment contract during create, update, and repin, then materialize pinned versions at start. Association tables currently live in the Agents domain, so changes to template-skill or agent-skill relationships cross all three domains.

## Primary flows

### Publish a template version

Validate referenced skills, create the next immutable custom version, copy omitted fields and retained requirements, then expose it as the latest lineage version. Existing agent pins remain unchanged.

### Apply a Template Update

For an organization fork with a newer Platform Template Version available, an explicit Template Update clones the complete newer platform snapshot—including content and required skills—into the next organization version. Organization customizations are intentionally replaced by the platform snapshot. The original fork origin remains intact, the stored platform baseline ID/version advances to the adopted platform version, and existing Agent pins remain unchanged.

### Apply a source update to an Agent Override

An Agent Override may show an update only from the direct Platform or Organization lineage of its Override Source Version. The user explicitly selects the complete newer source snapshot as the Agent's shared pin; a stopped Agent changes pins immediately and a running Agent uses Apply & Restart. Source updates never mutate or merge local Override Draft edits, never publish an Override Version, and an unavailable source does not invalidate an existing self-contained Override snapshot.

### Assign and mount skills

Explicit assignments are persisted after Agent visibility and provider requirements pass, each pinning the requested Skill Version or the latest published version at apply time. Agent start loads the assigned pinned snapshots, adds eligible supported aai-cli Skills, builds the runtime manifest with each Skill's isolated `aai-<integration>`/slug prefix, and appends pointers to the rendered tool context. Hermes reconstructs `/workspace/skills`; OpenClaw reconstructs `/home/node/.openclaw/workspace/skills`.

### Fork a built-in skill

An Organization manager can fork any visible Platform Skill, including a bundled aai-cli Skill, from its read-only detail page. `POST /{skill_id}/fork` creates an Organization-owned lineage with an unpublished draft containing the source's complete file tree and exact source-version reference. Agent owners can similarly fork a visible Platform or Organization Skill into an Agent-private lineage. The source remains immutable and existing pins never move. Apply Update either publishes the newest direct source immediately or replaces the current draft and leaves it unpublished for review.

### Delete a Skill lineage

From the owning scope, a manager can use `DELETE /{skill_id}` to permanently remove a custom Skill's draft, every published version, and all version files when no Agent is assigned any version of the lineage. Template and Agent Template Override requirements, and fork-source provenance, also block deletion so those resources are never silently invalidated. Built-in `aai_cli` Platform lineages remain protected. The API checks every `AgentSkill` row, including retained pins belonging to soft-deleted Agents, and the database cascades only the deleted lineage's own child rows.

### Delete a version

A manager can delete a published version only when it is not the last version and no Agent pin, Template/Override requirement, draft, or fork source references it. Platform versions are managed through Platform Skill APIs; Organization and Agent version deletion is scoped to the owning resource. Deleting an unreferenced historical version never affects Agents because runtimes mount exact pinned snapshots.

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
| Built-in skill seeding              | `../../api/domains/skills/skill_seeder.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`                         |
| Assignment enforcement and mounting | `../../api/domains/agents/service.py`, `../../api/domains/agents/scripts/hermes/start.sh`, `../../api/domains/agents/scripts/openclaw/init-openclaw.js` |
| UI template surface                 | `../../ui/src/features/agents/components/templates-panel.tsx`, `../../ui/src/features/platform-templates/`                     |
| UI skill surface                    | `../../ui/src/features/skills/` (scope-parameterized list/detail/new, reused across all three scopes via `scope.ts`), `../../ui/src/features/agents/components/agent-skills-tab.tsx` (always-visible Agent assignment editor with debounced API search and infinite loading), `../../ui/src/features/agents/components/agent-skill-detail-page.tsx`, `../../ui/src/features/skills/components/platform-skills-page.tsx` |
| Tests                               | `../../api/tests/integration/test_templates.py`, `../../api/tests/integration/test_skills.py`, `../../api/tests/integration/test_agents.py` |

## Change impact

Template changes affect agent pinning/rendering, predefined seeds, required skills, UI template schemas, and existing-version behavior. Changes to predefined v1 requirements must account for already-pinned agents. Agent Template Override changes additionally affect Agent-owned snapshot persistence, source update discovery, pin selection, restart activation, rollback, and sibling isolation. Skill changes affect file path validation, version publishing, lineage/version-deletion protections, agent start manifests, provider requirements, templates, and the Skills UI; provider-requirement edits must account for existing assignments. Skill forking adds a built-in detail-page action and a `POST /{skill_id}/fork` contract; custom-lineage deletion adds scoped `DELETE /{skill_id}` contracts with cross-resource reference checks, while version deletion remains `DELETE /{skill_id}/versions/{version}`; and agents now pin an exact skill version (`agent_skill.pinned_version`, exposed on `AgentAssignedSkillRead`), so start-time mounting and the agent configuration Skills UI resolve and edit pinned versions. Verify all three domain test suites when their relationship changes.

Required-skill *group* changes (the `group_key` column and the "at least one of" model) affect: agent create/update validation (group membership, the never-drop-to-zero grandfathering rule), predefined seeding idempotency (a group's seeded membership can be a subset when not all member skills exist yet), the hire dialog (multi-select group UI, gates Hire until a choice is made), the template editor (group authoring: create/add/remove member/dissolve), and the canonical Agent configuration page's Template selection flow (group choice re-derived against the new template's groups). Changes here must be verified against both `agent_template_skill` and `platform_template_skill` groups.
