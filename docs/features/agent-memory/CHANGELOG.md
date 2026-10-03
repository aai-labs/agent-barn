# Agent Memory — change log

Status: Active
Epic: Hindsight Agent Memory (no ticket yet)
Related context: [`../agent-memory.md`](../agent-memory.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../costs.md`](../costs.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

## Current state

- Delivered: the per-Agent memory opt-in and Memory Grants with audit Domain Events;
  authenticated gateway with current grant checks; hashed per-start Agent credentials; optional
  Hindsight and gateway Helm deployments; automatic Hermes/OpenClaw recall and retain alongside
  native memory for opted-in starts.
- In transition: runtime configuration and pinned-image contracts are implemented, but the
  optional deployment remains off by default. Organization cost limits, deletion purge, and
  backup/restore are pending.
- Next, in order:
  1. Cost and limits: Hindsight calls LiteLLM with one platform key. Per-bank LLM usage syncs
     into `cost_record`, and the gateway refuses retain and reflect for an Organization over its
     Model Spend Limit.
  2. UI: an Agent memory toggle and an Organization memory-access settings page.
  3. Lifecycle: purge an Agent's memories and grants on deletion; Hindsight backups.
- Blockers: none.

## Changes

### 2026-10-03 — slice 3 — runtime plugin wiring

- Delivered: opted-in starts configure the bundled Hermes Hindsight provider and pinned
  OpenClaw plugin for automatic recall and completed-turn retain, preserving Hermes native
  stores and OpenClaw `memory-core`. Restarting after disabling removes stale provider settings
  without changing native memory. Bearer credentials remain in environment variables rather
  than persisted runtime configuration.
- Changed: runtime builders and startup scripts, a bounded authenticated gateway readiness
  wait, image-installed pinned clients, and the OpenClaw plugin manifest compatibility patch.
  Both runtime workflows run the real provider contracts; CI selects them for shared memory
  builder/startup/test changes. No new schema or public endpoint is introduced in this slice.
- Verified: Hermes runtime target passes all three tests (two memory contracts and existing
  Skill discovery); OpenClaw runtime target passes both memory contracts. The OpenClaw local
  probe image contains pinned core 2026.8.2, plugin 0.13.0, and client 0.8.6; Hermes was checked
  with the pinned upstream v2026.8.19 image and client 0.6.1. Tests use deterministic HTTP
  memory/model responses, exercising real runtime consumers rather than Hindsight extraction.
  All 387 selected memory, gateway, Agent lifecycle, builder, and runtime digest API tests pass,
  as do lint, formatting, types, migration-head, chart, workflow parsing, and documentation-link
  checks. The broad API rerun was interrupted after 324 passing tests; it was not completed.
  The complete base-image builds and their existing smoke suites remain CI checks.
- Follow-up: cost attribution and Organization spend enforcement (Next, item 1).

### 2026-10-03 — slice 2 — memory gateway and deployment

- Delivered: a separate memory HTTP process on port 8003, with per-Agent bearer authentication,
  bank derivation, forced tags, live grant/revocation checks, and a narrow operation allowlist.
  Recall and reflect use `any_strict`; retain forces `per_tag` observations. Documents are
  namespaced by Agent and private/Organization scope, and operation IDs by Agent. Unsupported
  response expansions, backend diagnostics, and client headers cannot expose other memories.
- Changed: migration `d7f4a92c1e83` adds the unique `agent.memory_key_hash` index. Opted-in
  starts mint and inject credentials, persisting only their hash; stop, disable, deletion, and
  subsequent starts invalidate gateway access. Agent pods do not mount service-account tokens.
  Optional Helmfile releases add Hindsight 0.10.2, authenticated API with control plane off,
  its own pgvector/PostgreSQL 18 PVC, and a gateway Deployment holding only the required backend
  Secret key. Local development and API CI include gateway/chart checks.
- Verified: 44 gateway HTTP tests pass, including sanitized Hermes/OpenClaw capture replay;
  all nine rewritten POST payloads validate in the pinned Hindsight 0.10.2 image. A local
  instance with external pgvector/PostgreSQL rejects missing, wrong, and Agent credentials,
  accepts the gateway backend key, and has no control-plane listener (LLM verification was
  skipped in this auth probe). Enabled/disabled chart and Helmfile renders, Compose credential
  placement, lint, format, types, migration-head, and documentation-link checks pass.
  The full API suite passes all 3,363 tests; the expanded 44-test gateway suite and final
  existing-Agent migration/audit-log checks also pass.
- Follow-up: Runtime plugin wiring (Next, item 1). Organization suspension cannot be enforced
  until that lifecycle state exists. The optional release remains off in deployment workflows.

### 2026-10-03 — slice 1 — memory opt-in and Memory Grants

- Delivered: `PUT /organizations/{organization_id}/agents/{agent_id}/memory`, gated by the new
  Agent Permission `agent.memory.manage` (locked Agent Owner role). `GET`/`POST`/`DELETE
  /organizations/{organization_id}/memory-grants`, gated by the new Organization Permission
  `memory.access.manage` (Owner and Admin). Events `agent.memory.enabled`,
  `agent.memory.disabled`, `agent.memory_grant.created`, `agent.memory_grant.revoked`.
- Changed: migration `c3e8a1f4d927` adds `agent.memory_enabled`, the `agent_memory_grant`
  table, and both Permissions (lifting the catalogue immutability triggers only around those
  inserts). Agent reads include `memory_enabled`.
- Verified: 39 memory integration tests, 3 focused migration checks, and the 34-test Agent
  RBAC/policy suites pass. The full API run reported 3292 passed, 4 skipped, and 12 failures;
  two permission expectations were updated and passed in the RBAC run, and the remaining
  10 plugin tests passed on rerun with the installed Node executable on PATH. Lint, format,
  type, migration-head, diff, and relative documentation-link checks pass.
- Follow-up: the memory gateway, delivered in slice 2.
