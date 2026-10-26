# Agent Add-ons — change log

Status: Active
Epic: Agent Add-ons (no ticket yet)
Related context: [Agent Add-ons](../agent-addons.md), [runtime and deployment](../../architecture/runtime-and-deployment.md), [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md), [platform oversight ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md), [add-on approval ADR](../../adr/2026-10-26-platform-administrators-approve-agent-add-ons.md)

An Organization Owner or Admin requests extra libraries or tools for one Agent, a Platform Administrator approves the exact request, and it is installed into that Agent at its next start, on top of its Hermes or OpenClaw runtime, without custom images.

## Current state

- Delivered: requesting, withdrawing and reviewing add-ons of five kinds (pinned pip and npm packages, a git commit, a checksummed download, a reviewed command), the `install-addons` init container with its cached, credential-free install into a per-Agent read-only volume, `pending_addons`, the "Add-on install failed" provisioning error, audit Events and emails, the Agent's Add-ons section and Platform → Add-ons (PR 1).
- In transition: nothing.
- Next: close the epic once PR 1 merges; the durable facts already live in [`../agent-addons.md`](../agent-addons.md) and the ADR.
- Blockers: none.

## Changes

### 2026-10-26 — Agent Add-ons PR 1 — request, review and install

- Delivered: Owners and Admins request an add-on for one Agent with a why, see each one's state and any rejection reason, and withdraw pending ones. Platform Administrators list every request across Organizations, then approve, reject with a reason, or revoke. Approved add-ons are installed at the Agent's next start into `/opt/addons`, read-only for the agent, and named in its `AGENTS.md`. "Pending: applies on restart" shows until then. A failed install puts the Agent in ERROR naming the add-on, with the install log in its Logs. Deleting an Agent withdraws its pending requests and deletes its add-ons volume.
- Changed:
  - Schema (migration `6fe963719ec9`): `agent_addons`; `agent_addon_email_receipt`; `agent.running_addons_hash`; the `agent.addon.manage` Permission row.
  - API: `GET`/`POST /organizations/{id}/agents/{agent_id}/addons`, `POST .../addons/{addon_id}/withdraw`; `GET /platform/agent-addons`, `POST /platform/agent-addons/{addon_id}/approve|reject|revoke`; `AgentRead.pending_addons`; `api/developer_docs/operations-v1.json`.
  - RBAC: `agent.addon.manage` for Organization Owners and Admins; no Agent Access Role grants it.
  - Events: `agent.addon.requested`, `.approved`, `.rejected`, `.withdrawn`, `.revoked` (Organization scope, Security Audit), and the `agent.addon_email.notification` handler.
  - Runtime: the `install-addons` init container, the `agent-<id>-addons` PVC (2Gi) and ConfigMap, the agent container's read-only mount and environment, and the `PATH` line in both `start.sh` scripts. The new `Agent` column and the provisioning change move the runtime configuration digest once; an Agent without add-ons gets an unchanged pod spec. Neither runtime image changes: both already have `uv`, `git`, Node and `npm`.
  - Command add-ons: run with `HOME=/opt/addons/home`, so a `curl | bash` installer works as pasted; the executables it leaves in HOME's usual bin directories are linked into `/opt/addons/bin`, never shadowing a command the runtime image has. A command that changes nothing in the volume fails. The install hash covers the install script, so a new script reinstalls every volume once.
  - Provisioning error: `ADDON_INSTALL_FAILED`. Pod readiness counts a crash-looping init container as crashed.
  - Decision: [Platform Administrators approve Agent Add-ons](../../adr/2026-10-26-platform-administrators-approve-agent-add-ons.md), superseding the platform-oversight ADR in part.
  - UI: Agent configuration → Add-ons and its request dialog; Platform → Add-ons, with its own rail entry.
  - Docs: [`../agent-addons.md`](../agent-addons.md), `CONTEXT.md`, the RBAC brief, domain events, agents, Agent Sizes, runtime and deployment, resource usage, platform administration, testing, the index.
- Follow-up: none.
