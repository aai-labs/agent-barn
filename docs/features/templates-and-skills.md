# Templates and Skills

## Read when

Read before changing template versioning, predefined template seeding, template Markdown fields, required skills, skill archives, skill provider requirements, or agent skill mounting.

## Role in the system

Templates provide versioned agent configuration; Skills provide packaged instructions and references. A template version can require skills, while each agent pins a template version and carries its own explicit skill assignments. Built-in catalogue content is a platform/global resource rather than belonging to a customer Organization.

## Template invariants

- Predefined templates are global platform resources in the `platform_template` table (no `organization_id`), seeded once at startup. Custom templates and org forks of predefined templates are organization-scoped in `agent_template` (`organization_id` NOT NULL).
- `platform_template` uniqueness is `(template_slug, version)`. `agent_template` uniqueness is `(organization_id, template_slug, version)`.
- Template visibility is unified: an organization sees global `platform_template` rows plus its own `agent_template` rows. Repository resolution checks org-scoped first, then platform, so an org fork (higher version) shadows the platform v1.
- Agents pin an exact template version via one of two mutually-exclusive FKs: `platform_template_id` (global predefined) or `agent_template_id` (org-scoped custom/fork). A CHECK constraint ensures exactly one is set, restoring DB-level referential integrity. Publishing a later version does not move existing agents.
- Creating a custom template starts at version 1. Updating a custom template inserts the next org-scoped version, preserves omitted content, and preserves required skills unless replacements are supplied.
- Editing a platform predefined template forks it into `agent_template` at version = platform v + 1, with `forked_from_platform_template_id` pointing at the platform row. The seeder only ever refreshes the platform v1 in place; org forks are never clobbered.
- Template name, slug, and source remain stable across versions. Template content consists of the configured Markdown artifacts: soul, identity, user, tools, agents, boot, bootstrap, and heartbeat.
- Required-skill associations are stored in `agent_template_skill` (org-scoped) and `platform_template_skill` (global), mirroring the template split.

## Skill invariants

- Built-in `aai_cli` skills are global Platform Resources; custom skills belong to one organization.
- Built-in skills cannot be updated or deleted through normal skill CRUD.
- Custom skill content is stored as a ZIP and validated for archive size, expanded size, entry count, encryption, compression ratio, absolute paths, and path traversal.
- A custom skill cannot be deleted while assigned to an agent or required by a latest template version.
- Template-required skills must be explicitly present on the agent.
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

### Assign and mount skills

Explicit assignments are persisted after organization access and provider requirements pass. Agent start loads those skills, adds eligible built-in provider skills, builds the runtime skill manifest, and appends skill pointers to rendered tool context.

## Source map

| Concern                             | Authoritative source                                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Template model and DTOs             | `../../api/domains/templates/models.py`                                                                                         |
| Template versioning and seeding     | `../../api/domains/templates/service.py`, `../../api/domains/templates/predefined/`                                                                         |
| Template persistence                | `../../api/domains/templates/repository.py`                                                                                     |
| Skill model and DTOs                | `../../api/domains/skills/models.py`                                                                                            |
| Skill archive and CRUD rules        | `../../api/domains/skills/service.py`                                                                                           |
| Built-in skill seeding              | `../../api/domains/skills/skill_seeder.py`, `../../api/domains/agents/aai_cli_skills/`                                                |
| Assignment enforcement and mounting | `../../api/domains/agents/service.py`                                                                                           |
| UI template surface                 | `../../ui/src/features/agents/components/templates-panel.tsx`, template hooks                                                   |
| UI skill surface                    | `../../ui/src/features/skills/`                                                                                                 |
| Tests                               | `../../api/tests/integration/test_templates.py`, `../../api/tests/integration/test_skills.py`, `../../api/tests/integration/test_agents.py` |

## Change impact

Template changes affect agent pinning/rendering, predefined seeds, required skills, UI template schemas, and existing-version behavior. Changes to predefined v1 requirements must account for already-pinned agents. Skill changes affect ZIP validation, assignment/deletion guards, agent start manifests, provider requirements, templates, and the Skills UI; provider-requirement edits must account for existing assignments. Verify all three domain test suites when their relationship changes.
