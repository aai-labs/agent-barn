# Agent Sizes — change log

Status: Active
Epic: Agent Sizes (agreed with Kalkidan Betre, 2026-10-21; no ticket yet)
Related context: [Agent Sizes](../agent-sizes.md), [runtime and deployment](../../architecture/runtime-and-deployment.md), [resource usage](../resource-usage.md), [platform oversight ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md)

Platform Administrators keep a catalog of CPU and memory sizes. Organizations they allow pick from it when hiring or later; a Platform Administrator can give one Agent its own size even where its Organization can't choose. Custom values are never typed in. Custom runtime images are separate work.

## Current state

- Delivered: the size catalog with platform CRUD and audit Events, the Platform Settings section, and builders reading the resolved size (PR 1). Organizations the platform allows choose a size on hire or on the Agent's profile, Owners and Admins only, with a `pending_size` restart-needed signal (PR 2). Agents that never chose run on the default, seeded as Standard with the values Agents always had.
- In transition: nothing; an `agent_size_set_by_platform` flag for PR 3 is not added yet.
- Next:
  - **PR 3, Platform per-Agent override.** A Platform Administrator gives one Agent a size, locking it for the Organization, with an amendment to the platform-oversight ADR. Depends only on PR 1, so it can ship before PR 2 if the Sally case is more urgent.
- Blockers: open questions with Kalkidan (none blocks PR 1 or PR 2): the name "Agent Size"; whether the platform override locks the size; separate requests and limits (assumed yes); whether a size choice warns or blocks above the remaining Capacity Limit headroom (PR 2 does neither; the quota error at start covers it); whether Agent Owners should choose too (PR 2: Organization Owners and Admins only); a 1Gi PVC for every size.

## Changes

### 2026-10-22 — Agent Sizes PR 2 — Organizations choose a size

- Delivered: a Platform Administrator sets which sizes an Organization may choose on the Platform Organization page. Its Owners and Admins pick one when hiring or change it on the Agent's Profile; the change applies at the next start, with a pending note meanwhile. Withdrawing or disabling a size leaves the Agents on it. Every other Agent runs on the default, exactly as before.
- Changed:
  - Schema (migration `3046153d9447`): `organization_agent_sizes`; `agent.agent_size_id` (null follows the default, `ON DELETE RESTRICT`); `agent.running_resources`, filled in for Agents already running with the default's values; the `agent.size.manage` Permission row.
  - API: `PUT /platform/organizations/{id}/agent-sizes`, `GET /organizations/{id}/agent-sizes`, `PUT /organizations/{id}/agents/{agent_id}/agent-size`; `AgentCreate.agent_size_id`; `AgentRead.agent_size_id`, `agent_size`, `pending_size`; `PlatformOrganizationRead.agent_size_ids`.
  - Rules: deleting a size any Agent row is on, soft-deleted ones included, is refused (`409`), checked under the size's lock.
  - RBAC: `agent.size.manage` for Organization Owners and Admins; no Agent Access Role grants it.
  - Events: `organization.agent_sizes.changed` and `agent.agent_size.changed` (Organization scope, Security Audit).
  - Runtime: provisioning resolves the Agent's own size and records `running_resources`; the new `Agent` columns and the provisioning change move the runtime configuration digest once, so running Agents are offered an update until they restart, with an unchanged pod spec for any Agent on the default.
  - UI: the Platform Organization Agent sizes card, the hire dialog's CPU & memory choice, the Profile's CPU & memory tile.
  - Docs: [`../agent-sizes.md`](../agent-sizes.md), agents, RBAC brief, domain events, runtime and deployment, resource usage, platform administration, `CONTEXT.md`.
- Follow-up: PR 3.

### 2026-10-22 — Agent Sizes PR 1 — size catalog and builders

- Delivered: Platform Administrators list, add, edit, enable or disable, reorder, make default and delete Agent Sizes under Platform → Settings → Agent sizes. Exactly one enabled default; the default can be neither disabled nor deleted.
- Changed:
  - Schema: `agent_sizes` (migration `dd9ef852a427`), seeded with Standard as the default.
  - API: `GET`/`POST /platform/agent-sizes`, `PATCH`/`DELETE /platform/agent-sizes/{id}`.
  - Events: `platform.agent_size.created`, `.changed` and `.deleted` (Platform scope, Security Audit).
  - Runtime: both builders take the agent container's `resources`; provisioning resolves the default size at each start. The init container keeps a fixed block at the pre-sizes values. This edits the provisioning code, so the runtime configuration digest moves once and every running Agent is offered an update until it restarts, with an identical pod spec.
  - UI: the Agent sizes settings section.
  - Docs: [`../agent-sizes.md`](../agent-sizes.md), runtime and deployment, domain events, `CONTEXT.md` (Agent Size), the index.
- Follow-up: PR 2 and PR 3 above.
