# Agent Memory — change log

Status: Active
Epic: Hindsight Agent Memory (no ticket yet)
Related context: [`../agent-memory.md`](../agent-memory.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../costs.md`](../costs.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

## Current state

- Delivered: Platform Admin memory model selection and live Hindsight switching; the Agent memory setting, Organization memory-access page, and read-only
  Agent Memory tab and Owner/Admin Organization Memory viewer; the per-Agent memory opt-in and Memory Grants with audit Domain Events;
  authenticated gateway with current grant checks; hashed per-start Agent credentials; optional
  Hindsight and gateway Helm deployments; automatic Hermes/OpenClaw recall and retain alongside
  native memory for opted-in starts; Organization attribution of memory model costs;
  retain/reflect gating against combined observed Organization spend; Organization Memory Read only or Read and write grants and an explicit shared writer command for both runtimes.
- In transition: runtime configuration and pinned-image contracts are implemented, but the
  optional deployment remains off by default. Deletion cleanup and durable retries
  are delivered; backups and restores are deferred by the maintainer.
- Next, in order:
  1. Bound tombstone retention after proving an in-flight retain/queued-job drain;
     first-pass priority is delivered, but repeat-sweep storage and load still grow.
  2. Backups and tested restore when requested; deferred for now.
- Blockers: none.

## Changes

### 2026-10-05 — final review CI launcher correction

- Fixed: the purge-launcher contract test runs its child process from the
  repository root, independently of pytest's working directory. The launcher
  now imports correctly when verification runs from `api/`, as CI does.
- Verified: reproduced the failing launcher test from `api/` before the fix;
  all 14 purge tests and API static checks pass afterward. Opus confirmed all
  six preceding remarks were resolved and made approval conditional only on
  this correction, with no further review required.

### 2026-10-05 — full-branch approval and non-blocking follow-ups

- Reviewed: Opus 5.5 approved the full branch at `2ea2dc5c` after independently
  checking the required fixes and killing all six review mutations.
- Addressed: its remaining non-blocking remarks. Test budget defaults are fixed
  independently of deployment configuration; memory-toggle HTTP errors are
  translated by the service; purge age comparison preserves timezone offsets.
  Runtime contracts pass the opt-in flag and discover writer instructions in
  `TOOLS.md`. Memory and cost documentation now place each contract in its
  corresponding section.
- Verification: 145 spend-limit, Organization budget, memory, purge, and spend-gate
  integration tests pass with the normal developer environment; API static
  checks and all five Hermes/OpenClaw runtime image contracts pass.

### 2026-10-04 — full-branch review integration and corrections

- Integrated: current staging spend limits, RBAC, Organization Settings, and
  migration history. Memory uses the effective Organization limit; per-Agent
  key limits remain scoped to runtime calls. Local budget snapshots run every
  five minutes alongside cost sync.
- Fixed: read-only shared-retain regression coverage, opt-in-only writer prompts,
  transactional toggle idempotence/deletion handling, non-ASCII credential
  refusal, and bank-wide entity-name suppression.
- Hardened: the gateway uses an explicit credential/settings allowlist; older
  purge tombstones back off to daily sweeps without losing late-job cleanup.
- Kept: applied migration history and a merge revision instead of resetting local
  databases. Backups/restores remain deferred; full Opus review completion is
  pending after Claude rate limits interrupted the initial pass. Its saved
  findings have been addressed and await independent re-review.

- Verified: 276 follow-up API tests, 15 pinned-backend/client contracts,
  57 browser scenarios, API/UI static checks, production UI build, migration
  and memory chart checks. The read-permission write mutation is rejected.

### 2026-10-04 — Platform Settings review follow-ups

- Resolved: the eight findings from the Platform Settings slice review. This
  entry records only that slice, not a full-branch approval.
- Finished: optional model/active-key entries in environment templates, shared
  browser data-support registration, and operations documentation wrapping.
- Verified: all five Platform Settings browser scenarios and UI static checks pass.

### 2026-10-04 — Opus quality review follow-ups

- Fixed: Compose and Helmfile share `MEMORY_DEFAULT_MODEL` between the API and
  Hindsight startup configuration. Direct charts expose `memory.defaultModel`.
  The gateway fetch timeout is one second; allowlist serialization is documented.
- Added: active-key rejection, missing model-capability, and custom-default tests.
  Both previously surviving review mutations now fail their intended assertions.
- Cleaned up: model settings use domain-named hook fields, valid definition-list
  markup, formatted JSX, and browser mocks in data-support. Operations and
  verification guidance now live under their applicable sections.
- Verified: 24 API/client/pinned-runtime tests, all five browser scenarios,
  API/UI static checks, memory chart checks, and Compose validation pass.

### 2026-10-04 — Platform Settings design alignment

- Changed: Platform Settings reuses the Organization settings header, sidebar,
  full-width summary card, and Edit footer. Agent Memory shows its saved model,
  platformwide scope, processing purpose, and Organization cost attribution.
  Editing exposes the searchable chooser; Cancel discards the draft.
- Verified: five browser scenarios cover edit/save/reload, cancellation, denied
  access, save retry, and catalog failure. UI lint/type checks pass.

### 2026-10-04 — Platform Settings UI

- Delivered: Platform Settings → Agent Memory with a searchable supported-model
  chooser, explicit platformwide scope, save/cancel, and inline failure/retry.
  Platform navigation and the administrator menu expose it; Organization Owners
  cannot render the controls or fetch the settings/catalog.
- Verified: all four browser scenarios and UI lint/type checks pass, including
  persistence after reload, permission denial, failed save retry, and unavailable
  catalog. The shared preview requires login; authenticated rendering is covered
  by the browser suite.

### 2026-10-04 — Platform memory model settings

- Delivered: Platform Admin settings API, supported model catalog, singleton
  persistence, and Platform audit events. Organization roles cannot manage it.
- Changed: the pinned Hindsight bridge fetches service-authenticated settings,
  preserves model snapshots for in-progress operations, and switches new work
  within five seconds. Dedicated-key allowlists expand without budget/spend
  changes; bank attribution remains intact. Migration `d83f291bc7a0` is required.
- Verified: 36 settings/catalog/key tests and both pinned provider contracts pass;
  API static, chart isolation, and migration checks pass. Local migration and
  bridge deployment are applied, with GPT-4.1-mini preserved. The live supported
  catalog and settings save succeeded; the backend fetched the persisted choice.

### 2026-10-04 — permission-scoped Agent tab and shared authorship

- Changed: the Agent tab lists private records, then all Organization Memory
  only with a current read/read-write grant. Revocation hides shared records
  including the Agent's own contributions; the Owner/Admin page keeps them.
- Fixed: shared writes carry `author:<id>` rather than the private access tag.
  Recall/reflect use exact private scopes and a separately granted shared scope.
  An operator repair retags legacy documents and invalidates their derived
  observations through Hindsight's document API. Purging covers both tag formats.
- Verified: the old viewer reproduces the revoked-access leak against Hindsight;
  the corrected grant/revoke, pagination, recall, multi-page retagging, observation
  invalidation, and purge contracts pass. 161 viewer/gateway/grant scenarios and
  13 purge scenarios pass; all 32 memory browser tests pass, including refresh
  after revocation and regrant. API/UI static checks pass. The local shared
  document was repaired; Alex's current Read only grant was preserved.
  No platform schema or version bump.

### 2026-10-04 — Organization viewer and reliable permission refusals

- Delivered: an Owner/Admin Organization Memory page in Organization Settings,
  with read-only shared records, search, pagination, and retry. The gateway derives
  only `scope:team` in the authorized Organization; a distinct signed operation
  cannot expand an Agent-history capability into Organization access.
- Fixed: both runtime Deployments mount the writer as an executable in
  `/usr/local/bin`, making the short name available even after shell PATH resets.
  Agent instructions require each save to be attempted and the actual refusal
  explained, rather than repeating historical tool-unavailable claims.
- Clarified: the Agent viewer is saved history, including shared contributions.
  Revocation keeps those records and human viewing authority separate from
  the Agent's live write/recall grants. Previously learned own facts are not erased.
- Verified: short-name discovery reproduced failing before the mount; five real
  runtime contracts pass after it, including a 403 through Hermes' terminal.
  161 viewer/gateway/grant API tests, the pinned Hindsight Organization listing
  contract, 59 tool/builder tests, and all 31 memory browser tests pass.
  API/UI static checks and memory chart checks pass. Alex was refreshed with
  its grant still revoked: a real Web Chat save attempt reports the gateway
  permission refusal; the live Owner viewer returns shared records only.
  No schema or version bump.

### 2026-10-04 — sharing form polish

- Changed: the sharing form uses a responsive card, full-width fields, short
  permission labels, contextual explanations, and a separate action footer.
  The settings sidebar now shrinks so its scrolling navigation does not push
  the memory form outside a narrow viewport.
- Verified: the 390px overflow regression failed before the sidebar fix; all
  26 memory browser tests pass afterward, including desktop/narrow card checks.
  Screenshots were inspected; UI lint/types pass.

### 2026-10-04 — terminal writer discovery

- Fixed: runtime instructions invoke the Organization Memory writer by its
  absolute installed path. Hermes terminal shells reset PATH, so the short name
  was unavailable even though startup installed it. Existing Agents need updated
  configuration and a restart for the corrected instructions.
- Verified: the real Hermes terminal reproduces command-not-found on the original
  instructions; all four runtime memory contracts pass after the fix. API static
  checks and 59 tool/builder tests pass. Alex was refreshed, and its terminal
  accepted the requested Organization name save through the authenticated
  gateway; a subsequent recall returns the Organization name.

### 2026-10-04 — combined Organization Memory permission

- Changed: Organization Memory offers Read only or Read and write, with one grant
  per Agent. Read and write permits both recall and explicit shared saves;
  cross-Agent access remains read-only. To change a permission, revoke and regrant.
- Migration: `c95f20b8413a` merges existing separate grants, preserving writer
  provenance; previous write-only grants gain read access. Downgrade preserves
  effective read/write authority as separate rows. Historical audit events remain valid.
- Verified: the recall regression failed before the fix and passes after it;
  124 API/schema tests, all 24 memory browser tests, API/UI static checks, and
  the migration-head check pass. The local database is upgraded.

### 2026-10-04 — explicit memory access UI

- Delivered: cross-Agent access is labeled read-only with an explicit statement
  that it cannot write or change the source Agent's memories. Organization Memory
  offers separate Read only and Write only grants, named grant actions, and
  separate list/revoke controls; creating a new grant defaults to read-only.
- Verified: UI lint/types and all 24 memory Playwright tests pass. The new flow
  proves explicit write selection and revocation without removing read access.
  The local database has been upgraded to the new grant schema.

### 2026-10-04 — explicit Organization Memory write access and tool

- Delivered: independent read/write grants, defaulting new grants to read-only.
  Cross-Agent grants cannot allow writes. The gateway requires write access for
  shared retains and the new content-only `organization-memory` endpoint.
  Both runtimes install `agentbarn-memory remember-organization` with instructions;
  automatic saves remain private, and accepted writes are asynchronous.
- Changed: migration `b84e19a7302f` preserves old combined grants as separate
  read/write rows; new audit payloads include access. Shared runtime code targets
  Python 3.12. Existing Agents need a restart for the tool; grants apply immediately.
- Verified: 119 API/gateway/schema tests, 59 tool/builder tests, and all four real
  runtime memory contracts pass. Static, migration-head, and chart checks pass.
  The runtime checks caught and fixed Python-version compatibility, and the probe
  fixture now invokes its driver only for gateway startup rather than health checks.
- UI: access mode schemas/actions and explicit permission controls are implemented
  and verified in the next UI commit. Backups/restores remain deferred.

### 2026-10-04 — memory Save and Restart

- Delivered: running Agents use **Save and Restart** when the user has lifecycle
  permission, reusing the shared stop/save/start flow. Stopped Agents stay stopped;
  users with memory permission alone can save with a manual restart explanation.
  Save and lifecycle failures remain inline without closing the editor as successful.
- Verified: UI lint/types and all 23 memory Playwright tests pass, including ordered
  lifecycle requests, restart failure, and saving without lifecycle permission.
  The browser run required the existing Playwright container and a fresh test build
  cache after host-library and cached-path failures.

### 2026-10-04 — local Hindsight backend

- Delivered: an opt-in `local-hindsight` Compose profile with authenticated
  Hindsight 0.10.2, the existing cost attribution bridge, and persistent
  pgvector/Postgres 18 storage. Backend/database ports remain unpublished;
  model/database credentials are excluded from the shared application environment.
- Configured: the local environment now uses this backend and a dedicated model
  key limited to $10 per 30 days; only its hash reaches cost attribution settings.
  Secrets remain in the ignored local `.env`.
- Verified: Hindsight health succeeds; missing/wrong API keys return 401, and the
  gateway key succeeds. Alex's authorized product API memory listing returns 200
  with zero items. Static, migration-head, shell, and chart/Compose checks pass.
- Follow-up: backups/restores remain deferred; restart opted-in Agents to activate
  the memory provider when needed.

### 2026-10-04 — local startup review

- Fixed: `./run.sh` now starts the Compose memory gateway alongside the other
  services and reports its port. The contributor docs explain the separate
  Hindsight backend prerequisite and local port overrides.
- Verified: shell syntax and memory chart/Compose checks pass. The local gateway
  starts and responds to its health probe; the viewer still returns 503 because
  this environment has no Hindsight backend URL/auth configured. Messaging
  connections are not required for memory viewing.
- Follow-up: configure a local or existing Hindsight backend for this environment.

### 2026-10-04 — slice 6 — deletion cleanup and retries

- Delivered: deletion atomically clears memory credentials, removes inbound/outbound
  grants, and queues a durable purge. The bounded job removes private/shared documents,
  retries failures with reclaimable leases, and retains hourly sweeps for late work.
- Changed: migration `a63e8c941d20` adds tombstones and backfills deleted Agents.
  The enabled chart adds a five-minute cleanup job with only database/backend auth;
  local operators use `make purge-agent-memory`. No public delete tool or version bump.
- Reviewed: grant creation locks and rechecks both Agents to prevent insertion after
  concurrent deletion. Additional checks cover partial deletion recovery, absent banks,
  minimal operator credentials, and migration backfill/rollback. The wildcard contract
  now accounts for generated context being searchable alongside memory text.
- Verified: 13 cleanup integration tests and a real pinned Hindsight purge contract
  pass, preserving another Agent and bank. The broad regression run passed 406 tests;
  its wildcard assertion was corrected and passed on rerun. The focused memory/grant
  suite passed 50 tests; the final cleanup, pinned listing/purge, and schema run passed
  all 44 tests. Static, migration-head, and enabled/disabled chart checks pass.
- Follow-up: backups/restores are explicitly deferred. Physical purge is asynchronous;
  previously accepted retains are caught by subsequent sweeps.

### 2026-10-04 — slice 5 review — viewer navigation

- Changed: previous-page data is retained only for the same Organization and Agent.
  An empty later page keeps a way back when Hindsight's saved rows have changed.
- Verified: independent parent review checks pass: 169 selected API tests (including
  the real pinned Hindsight listing contract), 20 memory UI Playwright tests, API/UI
  lint and types, formatting, migration-head, and enabled/disabled chart checks.
- Follow-up: lifecycle purge and backups; memory editing and deletion controls are
  outside the read-only viewer slice.

### 2026-10-04 — slice 5 — memory viewing UI

- Delivered: Agent configuration → Memory toggles `memory_enabled` (needs
  `agent.memory.manage`); Organization Settings → Memory access lists, creates, and
  revokes Memory Grants (Owners and Admins); the Agent page's Memory tab lists what that
  Agent itself wrote with type, private/shared label, mention date, search, and pagination
  (needs `activity.read`). Viewing is read-only; there is no edit or delete.
- Changed: `GET /organizations/{organization_id}/agents/{agent_id}/memory/items` calls a
  separate read-only viewer on the memory gateway (`/memory/view/v1/memories`) with a
  30-second capability signed for one Organization and Agent. Only the gateway holds the
  Hindsight key; the viewer forces the bank and `agent:<id>` tag, accepts only search and
  paging, and fails closed (502) on any row outside that filter. `MEMORY_VIEW_BASE_URL`
  addresses it (Compose, Makefile, chart Secret, `.env.spec`). The UI's Agent permission enum
  now includes `agent.memory.manage`, which the API already returned. No migration, schema, or
  release-version change.
- Verified: the pinned Hindsight 0.10.2 `memories/list` source and a real container run show
  the tag filter applies before `total`, search is an ILIKE on text and context, and pagination
  is scoped to the filtered set; `test_agent_memory_viewer_contract.py` asserts this against
  the image. Viewer API tests cover permissions, hidden/deleted/other-Organization Agents,
  forged parameters, capability audience/expiry/forgery, stopped and disabled Agents, and
  upstream failures. Playwright covers the toggle, grants, viewer, read-only behavior,
  permission query guards, Organization cache isolation, and error states.
- Limitation: Hindsight 0.10.2 exposes no creation time on its list endpoint, so memories show
  `mentioned_at` rather than when they were stored; search also matches context that is not
  shown. The grant form lists at most 200 Agents.
- Follow-up: lifecycle purge and backups.

### 2026-10-03 — slice 4b — observed Organization spend limits

- Delivered: retain and reflect stop at the combined runtime snapshot and persisted
  memory spend limit (429), or pause for missing/stale accounting (503). Recall remains
  available. Zero, uncapped, changed limits, and renewed windows apply on the next request.
- Changed: migration `f2a8d41b9c63` adds a successful spend-log sync heartbeat, including
  empty successful runs; failed/truncated paging cannot refresh it. The enabled gateway
  chart requires attribution hashes. The gateway reads persisted policy/accounting without
  additional upstream credentials. No public DTO or release-version change.
- Verified: 273 selected gateway, memory spend, cost, and Organization-budget tests,
  plus both cost migration upgrade/rollback checks pass. Lint, formatting, types,
  migration-head, enabled/disabled chart checks, and the pinned launcher's CLI pass.
- Follow-up: UI, then lifecycle. This cutoff uses observed spend; late billing, healing,
  concurrent requests, and already queued consolidation can exceed the limit. Runtime
  budget banners and alerts still report runtime spend.

### 2026-10-03 — slice 4a — billed memory cost attribution

- Delivered: Hindsight model calls carry their server-controlled bank to LiteLLM;
  cost sync trusts this marker only for dedicated platform keys, writes exact
  Organization memory charges once, and keeps OpenRouter healing/replay protection.
- Changed: migration `e4c9b72a6f10` adds `cost_record.is_memory` (existing rows false).
  The Hindsight chart runs a pinned startup bridge with a concurrent-bank HTTP contract.
  Helmfile passes only key hashes into shared API configuration; retired hashes can
  be retained for rotation. No memory trace/content is ingested.
- Verified: 51 selected API tests pass, including pinned Hindsight foreground/background
  requests, cost sync policy, PostgreSQL persistence/healing/replay, renewal-window
  isolation, and migration rollback. Lint, format, types, migration-head, and charts pass.
- Follow-up: the gateway spend-limit gate, then the UI and lifecycle slices.

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

## PR #265 review corrections

Operator jobs boot from their documented minimal environment. New deletion purges
precede repeat sweeps, and viewers poll once per minute with focus refresh.
Organization memory processing uses an encrypted virtual key on the runtime
LiteLLM team; historical shared-key charges reduce its allowance and appear in
budget alerts. The pinned bridge fails closed when new bank credentials cannot
be refreshed. A partial memory-cost index supports the spend check. Pinned
backend tests document pre-repair legacy observation exposure and verify that
consolidation is queued before retain returns.

Opus review tightened credential isolation: settings now use a separate service
key and internal port 8004, absent from public API routes. Memory key creation
verifies team enrollment and revokes a key when verification fails. Retag tests
also prove that PATCH queues fresh consolidation before returning.
