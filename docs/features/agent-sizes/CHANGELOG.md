# Agent Sizes — change log

Status: Active
Epic: Agent Sizes (agreed with Kalkidan Betre, 2026-10-21; no ticket yet)
Related context: [Agent Sizes](../agent-sizes.md), [runtime and deployment](../../architecture/runtime-and-deployment.md), [resource usage](../resource-usage.md), [platform oversight ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md), [platform override ADR](../../adr/2026-10-22-platform-administrators-set-an-agents-size.md)

Platform Administrators keep a catalog of CPU and memory sizes. Organizations they allow pick from it when hiring or later; a Platform Administrator can give one Agent its own size even where its Organization can't choose. Custom values are never typed in. Custom runtime images are separate work.

## Current state

- Delivered: the size catalog with platform CRUD and audit Events, the Platform Settings section, and builders reading the resolved size (PR 1). Organizations the platform allows choose a size on hire or on the Agent's profile, Owners and Admins only, with a `pending_size` restart-needed signal (PR 2). A Platform Administrator lists every Agent on Platform → Agents, grouped by Organization, overrides one Agent's size, which locks it for the Organization until cleared, and restarts any Agent to apply it (PR 3). Agents that never chose run on the default, seeded as Standard with the values Agents always had.
- In transition: nothing.
- Next: close the epic once PR 3 merges: the durable facts already live in [`../agent-sizes.md`](../agent-sizes.md) and the ADR.
- Blockers: open questions with Kalkidan (none blocks a PR): the name "Agent Size"; separate requests and limits (assumed yes); whether a size choice warns or blocks above the remaining Capacity Limit headroom (neither; the quota error at start covers it); whether Agent Owners should choose too (Organization Owners and Admins only); a 1Gi PVC for every size; whether an override should be able to pick a disabled size (no) and whether the Organization should see who set it (it sees "Set by platform").

## Changes

### 2026-10-26 — Agent Sizes PR 3 — review follow-ups

- Delivered: making a size the default no longer takes it away from Organizations that were allowed it: the old default takes its place in their allowed sets, so each keeps the same choices. A size chosen on hire is audited. A choice, on hire or later, is re-checked under its locks, so a size disabled or withdrawn while it saves is refused. Platform Settings asks before switching the default or disabling a size Agents are on, and the Platform Organization card says how many Agents stay on a size before it is withdrawn.
- Changed:
  - API: `AgentSizeRead.agent_count` and `following_agent_count`; `GET /platform/agent-sizes?organization_id=` scopes them.
  - Events: `agent.agent_size.changed` on hire, in the `agent.created` correlation; `organization.agent_sizes.changed` for each set a default switch swaps, in its correlation.
  - Docs: [`../agent-sizes.md`](../agent-sizes.md) (default switch, under-lock re-check, restarting a pending size), domain events, the RBAC brief.
- Follow-up: none planned. Kept as documented after review: changing the default moves every Agent that follows it, withdrawing or disabling leaves Agents on a size, and whoever may restart an Agent applies its pending size.

### 2026-10-22 — Agent Sizes PR 3 — Platform per-Agent override

- Delivered: Platform → Agents lists every live Agent, one group per Organization, with its runtime, status and size, searchable and filterable by Organization. A Platform Administrator gives one Agent any enabled size, even one its Organization can't choose; the Organization then sees it as "Set by platform" and can't change it until the override is cleared, which puts the Agent back on the default. Overriding never restarts the Agent: the size applies at its next start, pending meanwhile. A Platform Administrator can restart any Agent from the same page, or start one that is not running, as the epic's acceptance criteria require.
- Changed:
  - Schema (migration `8b2e4f61c9d3`): `agent.agent_size_set_by_platform`, false for every existing Agent.
  - API: `GET /platform/agents`, `PUT /platform/agents/{agent_id}/agent-size`, `POST /platform/agents/{agent_id}/restart`; `AgentRead.agent_size_set_by_platform`; the Organization's size route answers `409` while an override stands.
  - Events: `agent.agent_size.changed` gains `by_platform` (false when absent, so earlier records still read).
  - Decision: [platform administrators set one Agent's size](../../adr/2026-10-22-platform-administrators-set-an-agents-size.md), superseding the platform-oversight ADR in part.
  - Runtime: the new `Agent` column moves the runtime configuration digest once more, with an unchanged pod spec.
  - UI: the Platform Agents page, its override dialog and its Restart/Start action; the Profile's CPU & memory tile shows a platform-set size locked.
  - Docs: [`../agent-sizes.md`](../agent-sizes.md), the RBAC brief, domain events, platform administration, the index, `CONTEXT.md`.
- Follow-up: none planned.

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
