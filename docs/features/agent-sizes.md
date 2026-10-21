# Agent Sizes

## Read when

Read before changing the Agent Size catalog, its Platform Settings section, how an Agent's CPU and memory are resolved at start, or the init container's fixed resources.

## Role in the system

An **Agent Size** is a named amount of CPU and memory, as a request and a limit, from a catalog that Platform Administrators keep. Every Agent runs on one. Nobody types in custom values: a size is picked from the catalog.

The catalog is being delivered as the Agent Sizes epic ([`agent-sizes/CHANGELOG.md`](agent-sizes/CHANGELOG.md)). Today every Agent runs on the catalog's **default** size. Organizations choosing a size, and a Platform Administrator giving one Agent its own, are later slices.

## The catalog

- Stored in `agent_sizes`: a unique `name`, `cpu_request_millicores`, `cpu_limit_millicores`, `memory_request_bytes`, `memory_limit_bytes`, `enabled`, `is_default` and `sort_order`.
- The migration that created the table seeded **Standard** as the default: requests 320Mi / 50m, limits 1Gi / 500m, the values Agents always ran with. Every Agent therefore kept exactly its resources when sizes arrived.
- Requests and limits are stored apart because the namespace quota binds on `requests.memory`: the request decides how many Agents fit and is what the cluster reserves; the limit is how far one may grow before it is throttled (CPU) or OOMKilled (memory).

## Invariants

- **Exactly one default, always enabled.** A partial unique index allows one default and a check constraint refuses a disabled one. The default can be neither disabled nor deleted (`409`); making another size the default is how it changes. That switch clears the old default and sets the new one in one transaction with both rows locked, so concurrent switches cannot leave none or two.
- **A size must be enabled before it becomes the default** (`409`), and `is_default: false` is refused (`422`): a size stops being the default only when another becomes it.
- **Values that can run.** Requests and limits are positive, each request is at most its limit, CPU is at most 64 cores and memory at most 256Gi. The database checks the first two as well. An edit is checked against the values it keeps, so raising only a request above the stored limit is refused (`422`).
- **Names are unique, ignoring case and surrounding space** (`409`).
- **A size an Agent is on can only be disabled, not deleted.** No Agent references a size yet; `AgentSizeRepository.is_referenced` is where that check lands when Agents can be given one.
- **Read at every start.** Provisioning resolves the size when the Agent starts, so editing a size, or changing the default, reaches each Agent on it the next time it starts and never touches a running pod. This does not move the runtime configuration digest, so no update is offered for it; see [runtime and deployment](../architecture/runtime-and-deployment.md#runtime-configuration-digest).

## API

All under `require_platform_admin`, which refuses writes from a read-only API key. The catalog is a Platform Resource with no Organization-scoped equivalent.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/agent-sizes` | The catalog, by `sort_order`, then name |
| `POST /api/v1/platform/agent-sizes` | Adds a size; it is never the default on creation (`201`) |
| `PATCH /api/v1/platform/agent-sizes/{id}` | Edits values, enables or disables, renames, reorders, or makes it the default (`is_default: true`) |
| `DELETE /api/v1/platform/agent-sizes/{id}` | Removes a size that is not the default (`204`) |

Each change is audited: `platform.agent_size.created`, `.changed` (one per field that moved; a default switch records both sides in one correlation) and `.deleted`, Platform scope, Security Audit. A save that changes nothing records nothing. See [domain events](domain-events.md).

## How a size reaches the pod

`AgentService._provision_and_start` asks `AgentSizeLookupService.resolve()` for the Agent's size (the default today) and passes it to the runtime builder as the agent container's resources, rendered by `container_resources` in the units the builders always wrote (`320Mi`, `1Gi`, `50m`, `500m`). The root `fix-pvc-owner` init container keeps a fixed block at the pre-sizes values instead; why is in [runtime and deployment](../architecture/runtime-and-deployment.md). The PVC stays 1Gi for every size.

## The settings section

Platform → Settings → **Agent sizes** (`?section=agent-sizes`) lists the catalog with CPU and memory as limit over request, an enabled switch (fixed on for the default) and a Default badge. A size is added or edited in a dialog in vCPU and MiB; the dialog checks the same rules as the API before sending and shows the API's refusal in place. Make default and Delete are in each row's menu, and Delete asks to confirm. Neither is offered for the default.

## Source map

| Concern | Source |
| --- | --- |
| Table, DTOs, bounds, seed values | `../../api/domains/agent_sizes/models.py` |
| Catalog writes and audit Events | `../../api/domains/agent_sizes/repository.py` |
| Rules | `../../api/domains/agent_sizes/service.py` |
| Resolution for provisioning | `../../api/domains/agent_sizes/lookup.py` |
| Routes | `../../api/domains/agent_sizes/routes.py` |
| Migration and seed | `../../api/migrations/versions/dd9ef852a427_add_agent_sizes.py` |
| Rendering into the pod | `container_resources` and `INIT_CONTAINER_RESOURCES` in `../../api/domains/agents/builders/common.py`; `build_deployment`, `build_hermes_deployment` |
| UI | `../../ui/src/features/agent-sizes/`, the `agent-sizes` entry in `../../ui/src/features/platform-settings/components/platform-settings.tsx` |
| Tests | `../../api/tests/integration/test_agent_sizes.py`, `../../api/tests/integration/test_agent_sizes_migration.py`, `../../api/tests/unit/test_agent_container_resources.py`, the builder unit tests, `../../ui/tests/e2e/platform-agent-sizes.spec.ts` |

## Change impact

A new size column is a migration, a DTO field, a change Event setting (`SIZE_SETTINGS`) and a dialog field. Changing how a size renders changes every Agent's pod spec at its next start, so keep Standard rendering the pre-sizes strings (`test_agent_container_resources.py`). Changing the init container's block changes what every Agent costs the quota.
