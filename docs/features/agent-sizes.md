# Agent Sizes

## Read when

Read before changing the Agent Size catalog, its Platform Settings section, which sizes an Organization may choose and who chooses them, the Platform Agents page or a Platform Administrator's per-Agent override, how an Agent's CPU and memory are resolved at start, `pending_size`, or the init container's fixed resources.

## Role in the system

An **Agent Size** is a named amount of CPU and memory, as a request and a limit, from a catalog that Platform Administrators keep. Every Agent runs on one. Nobody types in custom values: a size is picked from the catalog.

The catalog is being delivered as the Agent Sizes epic ([`agent-sizes/CHANGELOG.md`](agent-sizes/CHANGELOG.md)). An Agent runs on the size its Organization, or a Platform Administrator, chose for it, or on the catalog's **default** size. A Platform Administrator decides which sizes, if any, each Organization may choose; its Owners and Admins then choose when hiring or later. A Platform Administrator can also give one Agent any enabled size, which locks it for the Organization; see [Platform override](#platform-override).

## The catalog

- Stored in `agent_sizes`: a unique `name`, `cpu_request_millicores`, `cpu_limit_millicores`, `memory_request_bytes`, `memory_limit_bytes`, `enabled`, `is_default` and `sort_order`.
- The migration that created the table seeded **Standard** as the default: requests 320Mi / 50m, limits 1Gi / 500m, the values Agents always ran with. Every Agent therefore kept exactly its resources when sizes arrived.
- Requests and limits are stored apart because the namespace quota binds on `requests.memory`: the request decides how many Agents fit and is what the cluster reserves; the limit is how far one may grow before it is throttled (CPU) or OOMKilled (memory).

## Invariants

- **Exactly one default, always enabled.** A partial unique index allows one default and a check constraint refuses a disabled one. The default can be neither disabled nor deleted (`409`); making another size the default is how it changes. That switch clears the old default and sets the new one in one transaction with both rows locked, so concurrent switches cannot leave none or two.
- **A size must be enabled before it becomes the default** (`409`), and `is_default: false` is refused (`422`): a size stops being the default only when another becomes it.
- **Values that can run.** Requests and limits are positive, each request is at most its limit, CPU is at most 64 cores and memory at most 256Gi. The database checks the first two as well. An edit is checked against the values it keeps, so raising only a request above the stored limit is refused (`422`).
- **Names are unique, ignoring case and surrounding space** (`409`).
- **A size any Agent row is on can only be disabled, not deleted** (`409`). Soft-deleted Agents count: their rows still hold `agent.agent_size_id`, which the foreign key protects (`ON DELETE RESTRICT`), and keeping the size keeps their history describing a real one. The check runs under the size row's update lock, and choosing a size holds a share lock on it, so a delete cannot race a choice. Deleting a size that only allowed sets name withdraws it from them.
- **Read at every start.** Provisioning resolves the size when the Agent starts, so choosing another size, editing one, or changing the default reaches each Agent on it the next time it starts and never touches a running pod. This does not move the runtime configuration digest, so no update is offered for it; `pending_size` is the signal instead (below and [runtime and deployment](../architecture/runtime-and-deployment.md#runtime-configuration-digest)).

## Organization choice

- **The allowed set.** `organization_agent_sizes (organization_id, agent_size_id)` lists the sizes an Organization may choose beyond the default. No rows: it cannot choose, and the UI shows that as the "Can choose CPU & memory" switch turned off. The default is always choosable and never stored; a set sent with it drops it. Only a Platform Administrator changes the set: a bigger size spends shared cluster capacity, so an Organization cannot grant itself one.
- **Adding needs an enabled size** (`400`); a size already in the set may stay after it is disabled, which is how the Platform Organization page keeps showing it until someone withdraws it.
- **Who chooses.** `agent.size.manage`, an Organization role permission held by Owners and Admins. No Agent Access Role grants it, so an Agent's own Owner or Editor who is a Member cannot choose; see the [RBAC brief](rbac/IMPLEMENTATION-BRIEF.md).
- **What can be chosen.** The default, or an enabled size in the Organization's allowed set (`400` otherwise). Choosing the default stores `agent_size_id = NULL`, so the Agent keeps following the default wherever it moves. Re-sending the size an Agent is already on is a no-op even when that size can no longer be chosen.
- **Withdrawing or disabling a size leaves the Agents on it.** It only stops the size being chosen again; those Agents keep starting on it until someone chooses another.
- **A change never stops the Agent.** It applies at the next start. Choosing takes the Agent's lifecycle lock (`409` while a start, stop or other lifecycle operation holds it), because those paths can save the whole Agent row on failure, and writes only `agent_size_id` on the locked row.
- **`pending_size`.** At start, `agent.running_resources` records the requests and limits the pod got, alongside `running_model`; stop clears it. The migration that added the column filled it in for Agents already running with the default's values, since that is what they were started on. `AgentRead.pending_size` is true when a running Agent's recorded resources differ from those its size gives now, so choosing another size, editing the one it is on, or moving the default under it all read as pending until the next start.
- **Not over a platform override.** An Agent whose size a Platform Administrator set refuses the Organization's choice (`409`), for Owners and Admins alike, until the override is cleared.

## Platform override

A Platform Administrator gives one Agent a size from Platform View, so an Organization that may not choose (the platform's own default Organization, say) can still have one Agent on more memory. Why this one platform write on an Organization's Agent exists, and why it is no wider, is in [its ADR](../adr/2026-10-22-platform-administrators-set-an-agents-size.md).

- **Any enabled size.** The override is not limited to the Organization's allowed set, and may name the default, which holds the Agent on it even if the default moves. A disabled or unknown size is refused (`400`); re-sending the size an override already holds is a no-op even after that size is disabled.
- **It locks.** `agent.agent_size_set_by_platform` turns on with the size. The flag and the size are written together in `set_agent_size_with_event`, which re-checks the lock under the Agent's row lock, so an Organization choice cannot slip in between.
- **Clearing** (`null`) puts the Agent back on the default (`agent_size_id = NULL`) and turns the flag off; the Organization may choose again.
- **Never restarts by itself.** Like the Organization's choice it holds the Agent's lifecycle lock (`409` while one is held) and applies at the next start, with `pending_size` meanwhile.
- **A Platform Administrator can restart any Agent** to apply it, or start one that is not running (`POST /platform/agents/{agent_id}/restart`). That is the Agent's normal stop and start under its lifecycle lock, with the same managed-update and restore-point guards (`409`) and the same provisioning failure body; `agent.stopped` and `agent.started` name the administrator as actor. The Organization keeps its own lifecycle controls.
- **Audited** as `agent.agent_size.changed` with `by_platform: true`, Organization scope.

The **Platform Agents page** (Platform → Agents, `GET /platform/agents`) is where it is done: every live Agent across Organizations, ordered by Organization name and then Agent name and shown one group per Organization, searchable by either name and filterable to one Organization. Each row is Platform Oversight Data (name, runtime, status, size, whether the platform set it, whether it is pending), read through a fixed column list (`PlatformAgentRow`), never the Agent's configuration.

## API

The catalog and the allowed sets are under `require_platform_admin`, which refuses writes from a read-only API key.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/agent-sizes` | The catalog, by `sort_order`, then name |
| `POST /api/v1/platform/agent-sizes` | Adds a size; it is never the default on creation (`201`) |
| `PATCH /api/v1/platform/agent-sizes/{id}` | Edits values, enables or disables, renames, reorders, or makes it the default (`is_default: true`) |
| `DELETE /api/v1/platform/agent-sizes/{id}` | Removes a size that is not the default and no Agent row is on (`204`) |
| `PUT /api/v1/platform/organizations/{id}/agent-sizes` | Replaces the Organization's allowed set, `{agent_size_ids}`; answers with `PlatformOrganizationRead`, whose `agent_size_ids` lists it |
| `GET /api/v1/organizations/{id}/agent-sizes` | What the Organization can choose: `sizes` (the default first, then enabled allowed sizes in catalog order) and `can_choose`. Any member (`organization.read`) |
| `PUT /api/v1/organizations/{id}/agents/{agent_id}/agent-size` | Chooses the Agent's size, `{agent_size_id}`, or `null` for the default; answers with `AgentRead`. Separate from the Agent update so it is accepted while the Agent runs; `409` while the platform's override stands |
| `GET /api/v1/platform/agents` | Every live Agent, `PaginatedItems[PlatformAgentRead]`, by Organization name then Agent name; `search` (Agent or Organization name), `organization_id`, `page`, `page_size` (at most 100) |
| `PUT /api/v1/platform/agents/{agent_id}/agent-size` | The platform's override, `{agent_size_id}`: a size locks it, `null` clears it; answers with `PlatformAgentRead` |
| `POST /api/v1/platform/agents/{agent_id}/restart` | Restarts any Agent, or starts one that is not running; answers with `PlatformAgentRead` |

`AgentCreate.agent_size_id` chooses on hire with the same rules; omitted, the Agent is on the default and no permission beyond `agent.create` is needed. `AgentRead` carries `agent_size_id` (the stored choice), `agent_size` (the resolved size: id, name, values, `is_default`), `pending_size`, `agent_size_set_by_platform`, and `agent.size.manage` in `allowed_actions` for Owners and Admins.

The size route follows the RBAC brief: an Agent the caller cannot see is `404`; one they can see without `agent.size.manage` is `403`, re-checked through `AgentAuthorization.require_action` and the Organization grant.

Each change is audited, Security Audit, and a save that changes nothing records nothing. See [domain events](domain-events.md).

- Catalog: `platform.agent_size.created`, `.changed` (one per field that moved; a default switch records both sides in one correlation) and `.deleted`, Platform scope.
- `organization.agent_sizes.changed`: the allowed set before and after, ids and names, Organization scope, as the platform-set `organization.llm_budget.changed` is.
- `agent.agent_size.changed`: an Agent's size before and after (a null id and name mean the default), Organization scope; `by_platform` marks the platform's override and its clearing. A dedicated Event rather than a field of `agent.updated`: the size is written by its own route under its own permission, never by the general Agent update, so a stale general edit can never write a size back, and the payload names the sizes so the record still reads after one is renamed or deleted.

## How a size reaches the pod

`AgentService._provision_and_start` asks `AgentSizeLookupService.resolve(agent.agent_size_id)` for the Agent's size (its chosen one, else the default) and passes it to the runtime builder as the agent container's resources, rendered by `container_resources` in the units the builders always wrote (`320Mi`, `1Gi`, `50m`, `500m`). The root `fix-pvc-owner` init container keeps a fixed block at the pre-sizes values instead; why is in [runtime and deployment](../architecture/runtime-and-deployment.md). The PVC stays 1Gi for every size. A bigger size reserves more of the Organization's Capacity Limit at start; see [resource usage](resource-usage.md).

## The settings section

Platform → Settings → **Agent sizes** (`?section=agent-sizes`) lists the catalog with CPU and memory as limit over request, an enabled switch (fixed on for the default) and a Default badge. A size is added or edited in a dialog in vCPU and MiB; the dialog checks the same rules as the API before sending and shows the API's refusal in place. Make default and Delete are in each row's menu, and Delete asks to confirm. Neither is offered for the default.

## Organization surfaces

- **Platform Organization page** (Platform → Organizations → one Organization): the **Agent sizes** card, with the "Can choose CPU & memory" switch and a checkbox per enabled size besides the default. A disabled size the Organization still has stays listed, checked and marked, until it is unchecked; it cannot be checked again. Switching on needs at least one size before it saves.
- **Hire dialog**: a **CPU & memory** choice beside the runtime, shown only to Owners and Admins of an Organization that can choose, with the default preselected. Onboarding's hire step shares the form hook but not the field.
- **Agent configuration → Profile → Runtime & deployment**: the **CPU & memory** tile names the Agent's size (marked default when it follows it). Owners and Admins of an Organization that can choose change it there with a picker, saved at once; a size no longer offered shows as such and cannot be picked. "Pending: applies on restart" shows while `pending_size` is true, with a Restart button for whoever holds `agent.lifecycle.manage`. The Profile's own Apply & Restart is for its edit form and does not cover the size. A size the platform set shows with "Set by platform" and no picker.
- **Platform Agents page** (Platform → Agents): one card per Organization, linking to its Platform Organization page, with each Agent's runtime, status, size ("Set by platform" when overridden, the pending note) an **Override size** button, and **Restart** (or **Start** for an Agent that is not running), highlighted while a size is pending. Override's dialog offers the enabled sizes and, on an overridden Agent, **Clear override**; Restart asks to confirm, since it interrupts the Organization's Agent, and shows a failed start in the dialog.

## Source map

| Concern | Source |
| --- | --- |
| Tables, DTOs, bounds, seed values, `size_is_pending` | `../../api/domains/agent_sizes/models.py` |
| Catalog and allowed-set writes, the in-use check, audit Events | `../../api/domains/agent_sizes/repository.py` |
| Rules (catalog; allowed set and what an Organization can choose) | `../../api/domains/agent_sizes/service.py` |
| Resolution for provisioning and Agent reads, choosable sizes | `../../api/domains/agent_sizes/lookup.py` |
| Routes (platform catalog, platform allowed set, Organization read) | `../../api/domains/agent_sizes/routes.py` |
| Choosing an Agent's size, `AgentRead` fields, `running_resources` | `set_agent_size`, `_size_to_store`, `_build_agent_read` and `_provision_and_start` in `../../api/domains/agents/service.py`; `set_agent_size_with_event` in `../../api/domains/agents/repository.py` |
| Platform Agents list and override | `../../api/domains/agents/platform_service.py`, `../../api/domains/agents/platform_routes.py`; `find_platform_agents` and `get_platform_agent` in `../../api/domains/agents/repository.py`; `PlatformAgentRow`, `PlatformAgentRead` in `../../api/domains/agents/models.py` |
| Permission | `AGENT_SIZE_MANAGE` in `../../api/domains/rbac/catalog.py`; `allowed_actions` in `../../api/domains/agents/authorization.py` |
| Migrations | `../../api/migrations/versions/dd9ef852a427_add_agent_sizes.py` (catalog and seed), `../../api/migrations/versions/3046153d9447_let_organizations_choose_agent_sizes.py` (allowed sets, Agent columns, permission), `../../api/migrations/versions/8b2e4f61c9d3_platform_sets_an_agents_size.py` (`agent_size_set_by_platform`) |
| Rendering into the pod | `container_resources` and `INIT_CONTAINER_RESOURCES` in `../../api/domains/agents/builders/common.py`; `build_deployment`, `build_hermes_deployment` |
| UI | `../../ui/src/features/agent-sizes/` (settings section, Organization card, size picker, hooks), the `agent-sizes` entry in `../../ui/src/features/platform-settings/components/platform-settings.tsx`, `agent-size-tile.tsx` and the hire form in `../../ui/src/features/agents/`; the Platform Agents page in `../../ui/src/features/platform-agents/` |
| Tests | `../../api/tests/integration/test_agent_sizes.py`, `../../api/tests/integration/test_organization_agent_sizes.py`, the two migration tests, `../../api/tests/unit/test_agent_container_resources.py`, `../../api/tests/unit/test_agent_size_choice.py`, the builder unit tests, `../../ui/tests/e2e/platform-agent-sizes.spec.ts`, `../../ui/tests/e2e/organization-agent-sizes.spec.ts`; for the override, `../../api/tests/integration/test_platform_agent_sizes.py`, its migration test and `../../ui/tests/e2e/platform-agents.spec.ts` |

## Change impact

A new size column is a migration, a DTO field, a change Event setting (`SIZE_SETTINGS`) and a dialog field; one an Organization should see also goes in `AgentSizeOption` and its Zod schema. A new `Agent` column moves the runtime configuration digest once. Writing an Agent's size anywhere but `set_agent_size_with_event` skips its audit Event, its locks and the platform override's lock. A new Platform Agents column is an oversight-data decision under the platform-oversight ADR: add it to `PlatformAgentRow` deliberately, never by reusing `AgentRead`. Changing how a size renders changes every Agent's pod spec at its next start, so keep Standard rendering the pre-sizes strings (`test_agent_container_resources.py`). Changing the init container's block changes what every Agent costs the quota.
