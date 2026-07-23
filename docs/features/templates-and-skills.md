# Templates and Skills

## Read when

Read before changing template versioning, predefined template seeding, template Markdown fields, required skills, skill archives, skill provider requirements, or agent skill mounting.

## Role in the system

Templates provide versioned agent configuration; Skills provide packaged instructions and references. A template version can require skills, while each agent pins a template version and carries its own explicit skill assignments.

## Template invariants

- A template lineage is organization-scoped and identified by `template_slug`.
- `(organization_id, template_slug, version)` is unique.
- Agents pin an exact template version; publishing a later custom version does not move existing agents. System-managed predefined version 1 is the explicit mutable exception.
- Creating a custom template starts at version 1.
- Updating a custom template inserts the next version, preserves omitted content, and preserves required skills unless replacements are supplied.
- Template name, slug, organization, and source remain stable across custom versions.
- Template content consists of the configured Markdown artifacts: soul, identity, user, tools, agents, boot, bootstrap, and heartbeat.
- Predefined template seeding may refresh predefined version 1 content and required-skill associations in place; a lineage that has moved beyond that predefined state is not overwritten. Existing agents pinned to predefined v1 re-render changed content, but seeding does not reconcile their explicit skill assignments if requirements change.

## Skill invariants

- Built-in `aai_cli` skills are global; custom skills belong to one organization.
- Built-in skills cannot be updated or deleted through normal skill CRUD.
- Custom skill content is stored as a ZIP and validated for archive size, expanded size, entry count, encryption, compression ratio, absolute paths, and path traversal.
- A custom skill cannot be deleted while assigned to an agent or required by a latest template version.
- Template-required skills must be explicitly present on the agent.
- Agent create/update validates assigned-skill provider requirements against Agent Secrets. Editing a skill's required providers does not revalidate existing agent assignments, and start does not repeat that validation.
- At start time, eligible built-in provider skills are mounted implicitly when their provider credential exists. This does not create an explicit agent-skill assignment.

## Authorization invariants

- Template list, detail, and version-history APIs require the Organization Permission `template.read`; create and version-publishing APIs require `template.manage`.
- Skill list and detail APIs require the Organization Permission `skill.read`; custom Skill create, update, and delete APIs require `skill.manage`.
- The fixed Organization Member Role can read and use Organization Templates and Skills but cannot mutate their shared definitions. The UI preserves read-only drawers for Members and hides create/edit/delete controls; Organization Owner/Admin and superuser Organization context receive management authority.
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
