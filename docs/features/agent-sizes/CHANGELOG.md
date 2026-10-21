# Agent Sizes — change log

Status: Active
Epic: Agent Sizes (agreed with Kalkidan Betre, 2026-10-21; no ticket yet)
Related context: [Agent Sizes](../agent-sizes.md), [runtime and deployment](../../architecture/runtime-and-deployment.md), [resource usage](../resource-usage.md), [platform oversight ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md)

Platform Administrators keep a catalog of CPU and memory sizes. Organizations they allow pick from it when hiring or later; a Platform Administrator can give one Agent its own size even where its Organization can't choose. Custom values are never typed in. Custom runtime images are separate work.

## Current state

- Delivered: the size catalog with platform CRUD and audit Events, the Platform Settings section, and builders reading the resolved size. Every Agent runs on the default size, seeded as Standard with the values Agents always had, so nothing changed for any Agent.
- In transition: provisioning resolves only the default; `AgentSizeLookupService.resolve` already takes a size id, and `AgentSizeRepository.is_referenced` always answers false until Agents carry a size.
- Next:
  - **PR 2, Organization choice.** The sizes each Organization may choose, set by a Platform Administrator on the Platform Organization page; `agent.size.manage` for Owners and Admins; a size on hire and on the Agent's profile; `agent.agent_size_id`, a `running_resources` snapshot and a `pending_size` restart-needed signal, since editing a size does not move the runtime digest.
  - **PR 3, Platform per-Agent override.** A Platform Administrator gives one Agent a size, locking it for the Organization, with an amendment to the platform-oversight ADR. Depends only on PR 1, so it can ship before PR 2 if the Sally case is more urgent.
- Blockers: open questions with Kalkidan (none blocks PR 1): the name "Agent Size"; whether the platform override locks the size; separate requests and limits (assumed yes); whether a size choice warns or blocks above the remaining Capacity Limit headroom; a 1Gi PVC for every size.

## Changes

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
