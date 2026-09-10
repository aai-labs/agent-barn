# Agent Restore Points — change log

Status: Active
Epic: AF-292
Related context: [`../agents.md`](../agents.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md)

## Current state

- Delivered: server-side capture, list, read, restore, and delete of an Agent Restore Point, with
  reconcile-on-read resolving rows from live Job status, lifecycle guards on start and delete,
  and `agent.restore_point.*` Domain Events.
- In transition: nothing. The API surface is complete for Ticket 1 and safe to depend on.
- Next: Ticket 2 (reclaim stranded restore points and orphaned volumes) and Ticket 3 (the
  Agent configuration page section, plus opt-in replay of the captured configuration).
- Blockers: **Ticket 2 must ship in the same release as Ticket 1.** Ticket 1 resolves a row's
  status when someone reads it; a capture nobody ever reads keeps its row non-terminal until a
  read reclaims it, so restore points created and abandoned can hold a PVC indefinitely. The
  guards reconcile before evaluating, so this cannot make an Agent permanently undeletable, but
  it is a storage leak shipped alongside a storage feature.

## Changes

### 2026-09-10 — AF-292 — Ticket 1

- Delivered: `POST/GET …/agents/{id}/restore-points`, `GET/DELETE …/restore-points/{id}`, and
  `POST …/restore-points/{id}/restore`. Capture and restore run as Kubernetes Jobs on the API's
  own image against a stopped Agent.
- Changed: new `agent_restore_point` table, two enums, and a partial unique index
  (`a7c3e91d5b48`); new `api/domains/restore_points/` domain; `batch/v1` support and Job-log
  reads on `KubernetesClient`; `batch/jobs` and `pods/log` added to `k8s/agent-farm-user*.yaml`;
  `API_IMAGE` and four `RESTORE_POINT_*` settings wired through the chart; `agentbarn-api`
  chart `0.8.0` → `0.9.0`; `202` added to the status-code list in `guidelines/code.md`.
- Decision: the archive excludes credential material, boot-regenerated state, and the durable
  message spool, and retains each runtime's agent-owned `USER.md`. Restore performs its
  safety-net capture and its extraction in a single Job, because a `202` endpoint cannot wait
  for the first to finish and chaining two Jobs would add a state machine whose failure mode is
  an extraction that never starts.
- Decision: no new Permission keys — reads on `activity.read`, mutations on
  `agent.lifecycle.manage`.
- Observed: five defects in the original design were corrected during implementation — the
  status set could not represent an in-flight restore (added `RESTORING`); the retention cap
  would have blocked the Pre-Restore capture a restore itself creates; the `CASCADE` foreign key
  never fires because Agents are soft-deleted; restore point PVCs and Jobs are unreachable from
  `delete_agent`'s name-based teardown and are now found by label; and hostile archives were
  rejected only during extraction, i.e. after the wipe, which is now done during validation.
- Follow-up: Tickets 2 and 3. The end-to-end `make test-api-k8s` round trip against real volumes
  is written but has not been run against a disposable cluster with a rebuilt API image.
