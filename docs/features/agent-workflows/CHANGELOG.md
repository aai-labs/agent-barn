# AF-387 Agent workflows — change log

Status: Active
Epic: [AF-387](https://aai-labs.atlassian.net/browse/AF-387)
Related context: [Feature specification](../agent-workflows.md), [live architecture](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067248652), [RBAC](../rbac/IMPLEMENTATION-BRIEF.md)

## Current state

- Delivered: AF-388 manual authoring is merged through PR #308.
- In transition: AF-389 Agent-session text execution is in open PR [#326](https://github.com/aai-labs/agent-barn/pull/326) against staging. This AF-415 worktree starts at local head `6e109add`; neither PR merge nor deployment is implied.
- Implemented in AF-415 draft [PR #328](https://github.com/aai-labs/agent-barn/pull/328): shared Agent/chat/workflow artifact metadata, private Garage/S3 byte publication, scoped runtime CLI, signed links, Agent Files/run/step downloads, immutable handoff, reference retention and retryable purge. [Artifact contract](../agent-artifacts.md); [verification evidence](../agent-artifacts/EVIDENCE.md).
- Next: review and deploy AF-415 with private Garage configuration, then AF-390 approval integration. File-backed future reviews must pin exact IDs/checksums; URL expiry is independent of approval lifetime.
- Blockers: AF-389's uncertain-effect automatic retry, truthful stop/quiescence, live OpenClaw Agent-session acceptance and run-read-policy coordination remain open. Storage does not resolve them. Production Garage provisioning and rollout are separate authorized operational steps.

## Changes

### 2026-10-22 — AF-389 — update from latest staging

- Updated: Merged `origin/staging` at `d2cfca47` without text conflicts. Added no-op merge revision `b9e32d74a610` to join workflow head `f8740a67b788` with staging head `3bbf2465b9cb`; no data or schema operations are introduced.
- Verification: All 102 workflow run/authoring and trigger-server tests pass after repairing the migration graph. `make check-api`, `make check-migrations`, `make check-workflows` (Helm 3.19.0), and `git diff --check` pass. No new live Agent or browser run is claimed.

### 2026-10-22 — AF-389 — remove the workflow concurrency cap

- Changed: Removed the separate two-active-runs admission cap and its policy constant. Multiple runs of one or several workflows can start as sessions in the owning Agent; transactional start serialization and authorization remain in place.
- Documentation: Updated the feature contract and operations guidance; removed obsolete capacity tests in favor of acceptance beyond the former cap.
- Verification: Both updated acceptance tests failed against the original cap with HTTP 409. After removal, all 79 workflow run/authoring integration tests pass, along with `make check-api` and `git diff --check`.

### 2026-10-22 — AF-389 — synchronize the public Agent API guide

- Corrected: The developer guide now describes steps as sessions in the owning Agent, inheriting its current configuration. Removed stale reasoning-only rejection and runtime-image pinning claims. Clarified current permissions, attention-blocked runs, unavailable approval/resume operations and best-effort cancellation.
- Limits: Documented that failed/expired unfinished steps can currently retry automatically, dispatch deduplication does not guarantee exactly-once external effects, and the agreed uncertain-effect handling remains unimplemented. This documentation change does not change runtime behavior.
- Verification: Compared the guide with the start/read/cancel services, runtime dispatch, DTOs and controller; checked Markdown structure and whitespace. No application tests were rerun for this prose-only correction.

### 2026-10-23 — AF-415 — local independent-review corrections (not pushed)

- Fixed: completion credentials stay out of prompts/CLI arguments; runtime identity plus an owning-Agent attempt fence authorizes file publication. S3 I/O holds only the file lock; finalization reacquires run then file locks and fences intervening cancellation/deletion.
- Concurrency: overlapping publication/finalization uses nonblocking file locks; lock contention returns retryable 409 without failing another upload. The owning Agent trust boundary is explicit; there is no per-session isolation claim.
- Bounded: 16 staged/READY files per attempt and 16,000 bytes of file references per run. Unsafe purge targets record attempts/backoff, and pin release preserves deletion retry timing.
- Updated: RBAC runtime/background exceptions, attempt provenance, settled-run file polling, HTTP-only links, input validation and storage-disabled prompt behavior. Regression evidence and follow-up review are recorded with the artifact evidence.
- Review: Opus 5.5 approved the final local working tree with no Required findings; its 15 review regressions passed against PostgreSQL/Garage. The proposed whole-Agent trust boundary still awaits maintainer agreement.
- Delivery: these corrections remain local pending the maintainer's explicit agreement to push; PR #328 still contains the earlier revision.

### 2026-10-22 — AF-415 — [PR #328](https://github.com/aai-labs/agent-barn/pull/328) — shared Agent artifacts and file sharing

- Changed: Additive artifact/reference schema, private Garage-compatible S3 adapter, credential-derived runtime identity and current attempt/initiator fences. Published bytes are immutable and verified before READY.
- Delivered: one scoped CLI on both runtimes, ordinary chat publication, fresh signed links, Agent Files and workflow downloads alongside text results; active run pins and 30-day retention after release; deletion journals survive aggregate hard deletion.
- Operations: storage remains optional for text-only work. Documented service-only bucket access, limits, URL bearer semantics, migration/guarded rollback, recovery and bounded purge CronJob. No production provisioning, merge or deployment.
- Verification: see [evidence](../agent-artifacts/EVIDENCE.md), which distinguishes disposable real storage/runtime contracts from intercepted UI tests and unperformed live messaging/deployment acceptance.

### 2026-10-21 — AF-389 — PR preparation against latest staging

- Updated: Merged `origin/staging` at `58fcf60d` without conflicts, retaining the Teams identity, Hindsight hook permissions and navigation fixes. WF01 is already included in staging.
- Evidence: Captured [seven current UI screenshots](evidence/af-389/README.md) for explicit start, progress, cancellation, final and per-step text results, and mobile. These use synthetic browser fixtures and do not claim a new live Agent run.
- Verification: 219 workflow, trigger-server and merged Communications API tests and 76 workflow/navigation browser checks (including screenshot capture) pass after integration. API lint/format/types, UI types/lint, single migration-head validation and `make check-workflows` (default/custom kubeconfig Secret renders with Helm 3.19.0) pass. Full API/browser suites and live OpenClaw execution were not repeated.

### 2026-10-21 — AF-389 — address Opus review

- Fixed: The Helm worker now receives the same operator kubeconfig Secret and release namespace as the API and maintenance job. `make check-workflows` verifies both default and custom Secret renders; the testing guide replaces its removed fresh-Job suite command with this check.
- Capacity: Admission serializes per Agent across definitions and allows two queued/running/cancelling runs per Agent. Paused/blocked runs do not occupy capacity or block other Agents/Organizations.
- Runtime/UI: Structured replies are decoded independently of surrounding braces so explicit failed criteria remain failures. Hermes cancellation uses the original session key and honours cancellation received during start. Parked runs stop polling but still refresh on focus or mutation.
- Verification: Capacity isolation, parked-state capacity, structured-failure parsing, session-header and rendered worker assertions reproduce their original failures. Restoring parked-run polling makes all four new browser polling regressions fail. The fixed slice passes 106 workflow/trigger-server API tests, 53 workflow browser tests, API/UI lint/types, migration-head validation and default/custom-Secret Helm 3.19.0 renders (`make check-workflows`, using the local Helm image without networking). No live Agent execution or deployment was performed for these fixes.

### 2026-10-21 — AF-389 — redesign the result navigation card

- Changed: Result ready uses an icon, a View final summary subtitle and a chevron to identify it as navigation, with an accent background when selected. The selected-card connector and completion banner/content panel are retained. The panel heading is Run completed, without repeating Result ready. Active runs keep Run overview with a View run progress subtitle.
- Verified: All 16 workflow-run browser scenarios, UI type checks and lint pass, including final-summary navigation and the restored completion heading.

### 2026-10-20 — AF-389 — repair workflow worker wakeups

- Navigation: Workflow tabs now use `workflowView` in the URL, with `workflowRunPage` preserving run-list pagination. Reload and browser-history navigation restore the view. Breadcrumbs retain the workflow name, Runs returns to that workflow’s list, and the focused layout stays stable across workflow views.
- UI: Selecting a step in the rail opens its details in the main panel. On desktop, a subtle line and accent dot connect the selected navigation card to the panel. Result ready (Run overview before success) is the default and remains selectable. A compact Time taken card replaces Run activity, showing completed-step and total elapsed times from persisted timestamps, including waiting and retries. Unfinished steps show status rather than invented durations. Step-rail connectors align between adjacent markers.
- Copy: new start-history records use “Run started using version N”; the historical event API retains this wording; the run screen displays timing instead of event history.

- Fixed: starts, cancellation, results, failures and controller transitions now enqueue their committed wakeups immediately. Previously events remained pending in PostgreSQL, leaving local runs queued without a recovery pass.
- Verified: a regression reproduces the missing start enqueue and drives both steps through the real event processor without calling maintenance. Cancellation, failed-session retry and broker-outage recovery coverage also pass (95 focused tests total). The existing local Research run `01a15aed-e65f-7799-8a70-1ea41bb48001` completed both steps on Arlo after restarting its older trigger server; both result callbacks returned 204 and both summaries are persisted. Agent dispatch HTTP failures now identify the affected run in logs.
- Operations: existing Agents need a pause/start to load the workflow trigger route; the worker and recovery-pass documentation now describes Agent sessions consistently.

### 2026-10-20 — AF-389 — run steps as sessions in the owning Agent

- Changed: Workflow steps no longer run in isolated per-attempt Kubernetes Jobs. Each step runs as a new session in the running Agent, started through its private trigger server (port 8082), so the Agent's tools, Integrations, approval mode and spend limits govern it exactly as in chat. This follows the maintainer decision that workflows are governed by the Agent's configuration; AF-389 was updated to match.
- Removed: the Job builder and attempt runner, runtime image pinning (including the same-day local-image fallback), the per-attempt NetworkPolicy, the model relay route and model-call budget, the live Job test suite and its `test-workflow-runtime` target. Declared step capabilities no longer gate admission.
- Added: the trigger server's `workflow-steps` start/stop endpoints and step runner (Hermes `/v1/runs` events, OpenClaw `/v1/chat/completions`); `failure` callback (retry, or BLOCKED when the Agent asks for an approval); `dispatched_at` so a step is sent at most once. The event worker dispatches immediately; the scheduled pass recovers.
- Schema: unreleased `a38901e8a003` edited in place — `workflow_run` drops `image`, `model` and `profile`; `workflow_attempt` drops `model_calls` and adds `dispatched_at`.
- Configuration: `WORKFLOW_RUNTIME_BASE_URL` is now the Agent-pod callback. Local Compose derives it from `API_PORT`; the worker gets the k3d kubeconfig. Agents started earlier need one restart to load the new trigger server.
- Verification: 30 workflow-run, 18 trigger-server (one against a fake Hermes API), builder, workflow and public-contract tests (181 total) plus API lint/format/types and the migration-head check pass.

### 2026-10-20 — AF-389 — local imported runtime images

- Fixed: Starting a run on a local k3d installation failed with “The Agent's running image is not available yet” while the Agent was running, because images imported into k3d report only a bare `sha256:` config ID and no registry digest. With `ENVIRONMENT=local`, admission now pins the node-local image reference the running container reports. Other environments still require a registry digest.
- Changed: Start failures show one inline alert (fixed title plus the server's reason) instead of a nested error card.
- Verification: 60 Kubernetes-client, workflow-run and public-contract API tests (including a new local-image case), API lint/format/types, UI types/lint and 40 workflow browser tests pass. The running local Agent resolves to `docker.io/library/hermes-base:0.2.10`. A live model run was not started.

### 2026-10-20 — AF-389 — resolve tagged runtime images when starting runs

- Reproduced: both Hermes and OpenClaw tagged-image start regressions returned the screenshot's 409, “Workflow execution requires a runtime image pinned by digest”, at the expected HTTP assertion.
- Changed: admission resolves tagged images from the running Agent container's pullable Kubernetes image identity and saves the immutable image on the run. Existing explicit digest settings still work. Missing image evidence returns an actionable 409; Kubernetes lookup failure returns 503; neither queues work. Sidecars, terminating/stopped containers and bare CRI/config IDs cannot supply an image pin. No registry credentials, new environment fields or schema changes are needed.
- Verification: 129 Kubernetes/workflow/public-contract tests passed in the combined run; the two failure-case fixtures initially tagged the wrong runtime and both passed after correction. API lint/format/types and whitespace checks pass. Native model execution was not rerun for this admission change.


### 2026-10-20 — AF-389 — integrate latest staging

- Updated: Fast-forwarded this branch to `origin/staging` at `f2a933fa`, then restored the existing uncommitted text-only workflow changes. Combined workflow controller registration with Sync Provider wiring and kept both change-log histories. Run views now fit the shell-owned frame while retaining the mobile-header visibility behavior. Preserved staging's editor conflict notices, base-revision snapshots, capability caching and access-loss fixes.
- Schema: No-op merge `f8740a67b788` joins workflow execution `a38901e8a003` with staging `a4e9c2d7b615`; no database operation is performed by the branch update.
- Verification: API lint/format/types, UI types and focused lint, single-head/whitespace checks, 71 workflow/public-contract API tests and 40 workflow browser tests pass after restoration. The workflow changes remain uncommitted; the pre-update stash is retained as a recovery copy.


### 2026-10-20 — AF-388 — review follow-ups on PR #308

- Reproduced: after a 409, a failed capabilities refresh hid the Workflows tab and discarded the draft; "Load current revision" silently replaced another user's change and reported success in the error style; after a 403 the cached Agent permissions kept Save enabled; a 4,000-emoji description the API accepted failed UI response validation.
- Changed: a failed capability refresh keeps the last known state; loading the current revision lists what changed since the edit began in a neutral notice; a 403 refetches Agent permissions; length limits count code points and saved snapshots are read without input limits.
- Verification: four new browser tests fail without the fix and pass with it; 152 workflow, platform-setting and Agent detail browser tests pass; UI types and lint pass.

### 2026-10-19 — AF-389 — defer file artifacts and shared storage

- Changed: Reduced WF02 to isolated reasoning execution, durable progression/cancellation, per-step summaries and a final text result. Later steps receive completed text summaries from PostgreSQL. Removed artifact/storage implementation, environment/Helm fields, file API/UI, unshipped artifact tables/purge triggers and boto3 dependencies. Existing output-description fields remain compatible authoring metadata and guide text results. The runtime callback URL and module-owned bounds remain. Retention now applies only to settled text inputs/checkpoints/history.
- Follow-up: Shared S3-compatible storage, module-owned buckets and workflow file artifacts (publication, handoff, preview/download, retention and deletion) belong in a separate task/PR. The removed implementation is preserved only in an ignored local archive for reference; it is not part of the shipped scope.
- Verification: 71 focused workflow/settings/public-contract API tests and 36 browser tests pass. API/UI lint and types, formatting, migration-head and offline Helm renders pass. Both attempted live runtime tests exhausted their bounded retries after upstream model failures. A separate minimal request confirmed HTTP 401 with the existing test key; no live text-runtime pass is claimed. The disposable cluster was cleaned up, and prior file-based live acceptance is historical.


### 2026-10-19 — AF-389 — simplify configuration and share object storage

- Changed: Removed environment authoring/execution toggles. Platform Settings owns authoring, initially off; running saved versions remains independent. Execution availability requires the shared storage endpoint and credentials, alongside existing start-time authority/lifecycle/runtime checks. The shared S3-compatible client uses `STORAGE_S3_*`; workflows own the private `workflow-artifacts` bucket and fixed limits/retention in their module configuration. The runtime callback URL remains infrastructure configuration for isolated Jobs. Updated Helm/Helmfile, `.env.spec`, feature and operations guidance. Per-Agent workflow settings remain future work.
- Verification: 74 workflow/settings/storage integration tests and 2 public API contract tests pass, including real private Garage bytes, incomplete-storage denial and execution with authoring disabled. API lint/format/types and both offline Helm renders pass; rendered assertions cover shared storage, default/custom callback URLs, removed flags and retained NetworkPolicy. The live two-runtime suite was not rerun for this refactor; prior evidence below predates it.


### 2026-10-17 — AF-389 — run UI aligned to the design gallery

- Changed: Start, run detail, output preview and cancel confirmation now take the full page (no Agent header/tabs) and follow gallery screens 10, 11, 29, 30, 37 and 38 (run header and status badge, Steps rail, summary/outputs/activity cards, dedicated preview page, “Keep running”/“Cancel run”). Run state label `RUNNING` reads “Running”. Gallery elements with no WF02 data (record counts, connector names, approvals) are intentionally omitted. `ConfirmationDialog` gains an optional `cancelLabel`. Follow-up: the start screen reuses the run page's step rail and full-width card; the redundant back button is removed; outputs are one card; completed runs show the model's final summary (`final_summary` on run detail, read from the last checkpoint, no schema change); file preview is full width with Markdown rendering and a download-only card for other types. 27 workflow API tests, the public contract tests and 154 browser tests pass.
- Verification: 36 workflow browser tests, UI types and lint pass; screenshots were recaptured and compared against the gallery.

### 2026-10-17 — AF-389 — locally verified implementation

- Implemented in this worktree: explicit immutable-version/input starts with stable duplicate identities; durable run/attempt/checkpoint/history ledger and transactional Domain Event wakeups; fresh pinned native reasoning Jobs and current-authority/generation/deadline/model-call fences; private artifact staging/readback/SHA-256/READY, active references, 30/90-day retention and scoped soft-deletion purge; input/run/progress/history/cancel/file UI. Business actions and native commands remain rejected at admission. Original POCs and agreed UI sources are unchanged.
- Schema: additive `a38901e8a003` after `c32e42bb0396`. Approved workflow-owned cascades preserve existing aggregate deletion, with exact-key purge intents retained independently for operator cleanup. No live schema or data was changed during implementation.
- Verification: 72 affected migrated workflow/storage/public-contract API tests, 36 workflow browser tests, 130 existing chat/conversation/communication API tests, API lint/format/types, UI types/lint, single migration head and chart rendering pass. Real private Garage S3 tests prove byte/checksum validation, anonymous denial and exact-key deletion. Both digest-pinned native runtimes pass a two-step live artifact transformation using production APIs/ledger, migrated PostgreSQL and private S3; cluster probes verify fresh homes, absent control/service-account credentials, stale admission fencing and protected-canary/metadata/Kubernetes denial while the API remains reachable. The probe waits for bounded asynchronous CNI policy convergence; failed/interrupted harness attempts are not counted as acceptance evidence.
- Review: independent code-review-and-quality findings are resolved and the follow-up review is clear. Regressions cover stale concurrent admission, checksum-verified checkpoint handoff, paused-run stop/restart, duplicate paused wakeups and deletion-relative upload drain. The concurrency regression fails when its model-call bound is intentionally weakened and passes with the restored condition. Browser regressions cover Organization-switch cache/preview isolation and immediate concealment after a settled run's file request observes revoked access. Helmfile forwards configured bounds and retention as well as storage/admission settings.
- Verification limit: `make test-api` was interrupted before completing. The two observed `test_integration_isolation.py` failures (`backfill_preserves_routes_shared_sources_and_gateway_tokens` and `generation_downgrade_requires_stopped_sharepoint_and_retains_latest_rotated_grant`) both pass in a focused rerun; no full-suite pass is inferred. No version bump or unrelated AF-197 change.

### 2026-10-15 — AF-388 — CI audit projection test setup

- Reproduced: `ci-api / Test` failed because Redis was unavailable, leaving the workflow-setting event delivery pending. The audit test attempted processing without establishing its required enqueued state, so no projection was produced. The same assertion failed locally with `REDIS_URL=redis://127.0.0.1:1/0` before the fix.
- Changed: The test explicitly marks the persisted delivery enqueued before invoking the real processor, following neighboring audit tests, and asserts successful processing before checking the durable audit record. Production delivery/admission behavior is unchanged.
- Verification: The exact failing case and all 64 affected workflow/settings/public-contract tests pass with Redis still unavailable. API lint/format/types and whitespace checks pass. The full CI suite will rerun on the pushed fix.


### 2026-10-15 — AF-388 — [PR #308](https://github.com/aai-labs/agent-barn/pull/308)

- Evidence: Seven inspected screenshots are included in [PR #308](https://github.com/aai-labs/agent-barn/pull/308), covering editor/inputs, desktop/mobile saved cards, immutable-version history, Platform enablement and hidden disabled navigation. Screenshots remain PR evidence rather than repository files. The rendered UI uses synthetic request fixtures; three capture scenarios passed. No live persistence or execution is inferred from screenshots.
- Verification: Latest affected runs passed 64 workflow/settings/public-contract API tests, 29 Platform trial settings API tests and 148 workflow/Platform settings/Agent detail browser tests. API lint/format/types, UI types/lint, migration-head and whitespace checks passed; full suites were not repeated after the follow-ups.
- Scope: Excluded an unrelated inherited memory-test change from the PR diff. Excluded the MDP-119 research/prototype files and their index entry from the PR at the user’s request. No release or deployment changes accompany PR preparation.


### 2026-10-15 — AF-388 — hide disabled Workflows UI

- Changed: The Agent Workflows tab and its content require the enabled installation capability as well as Agent read permission. Disabled direct/legacy links fall back to an available Agent tab without fetching workflow content. A failed capability read hides the tab; existing capability-cache freshness still applies.
- Scope: UI visibility only, per user clarification. Existing API reads, mutation admission and saved data are unchanged.
- Verification: Both direct and legacy-link regressions failed on the visible tab before the fix, then passed. All 148 workflow, Platform workflow settings and Agent detail browser scenarios passed; UI types/lint and whitespace checks passed.


### 2026-10-15 — AF-388 — staging integration

- Changed: Merged staging through `fdb9b670`, preserving the uncommitted WF01 work. Platform Settings now extends staging’s existing composition with Workflows alongside Agent Memory and Signup & trials. Onboarding routes, trial cleanup and both sets of public API operations are retained.
- Schema: Merge revision `c32e42bb0396` joins workflow head `a38802d7f002` and staging head `d72b85f19c40`. The earlier migration-merge follow-up is resolved. Historical-schema preservation checks use SQL for columns present at that revision rather than the current Agent ORM model.
- Verification: 64 focused workflow/settings/public-contract API tests, 29 Platform trial settings API tests and 45 workflow/Platform Settings browser scenarios passed after integration. API lint/format/types, UI types/lint, the migration-head check and whitespace checks passed.
- Follow-up: WF01 remains pending review on the updated branch; merge/deployment coordination remains pending. No release or running database changes accompany the integration.


### 2026-10-15 — AF-388 — Platform workflow authoring setting

- Delivered: Platform Settings → Workflows provides an explicit Save/Cancel authoring toggle across Organizations. A saved choice overrides the environment default without a redeploy. Disabling authoring blocks creation, new versions and archive while preserving inspection; existing Agent authority remains required, and execution stays unavailable.
- Changed: Two Platform Admin GET/PUT operations, singleton settings migration `a38802d7f002` after `a38801c6e001`, atomic Platform-scoped audit events, effective capability/action checks and workflow-cache invalidation. The shared Platform Settings page now composes separate Agent Memory and Workflow sections.
- Verification: All 64 focused workflow, Platform Memory settings and public-contract API tests passed, including persistence, immediate admission, admin/read-only-key authority, audit projection/rollback and migration preservation. All 35 workflow and Platform Settings browser scenarios passed. API lint/format/types, UI types/lint, migration-head and whitespace checks passed.
- Follow-up: Generation and execution remain deferred. No release, deployment or runtime change accompanies this setting.


### 2026-10-15 — AF-388 — completion of query and validation follow-up

- Delivered: List/history page positions survive reload through validated URL parameters; returning from a definition retains the list page. Invalid page values fall back to page one, empty out-of-range pages offer first-page recovery, and legacy workflow links retain page parameters. List summaries and lazy query/cache behavior from the preceding improvement remain in place.
- Verification: Browser regressions first failed at the missing page URL parameters, then passed for reload, return navigation and invalid/out-of-range page recovery. All 26 workflow browser scenarios passed, including long and non-Latin labels persisting distinct valid internal keys without exposing them. The completion API run passed all 33 workflow/public-contract tests; API lint/format/types, UI types/lint and the migration-head check also passed. Earlier full-suite results below predate these improvements.
- Follow-up: No new review was started. The delegated improvement run ended at the Claude provider limit; no final Opus opinion is claimed for these improvements. No execution/generation, release or deployment changes accompany this follow-up.


### 2026-10-15 — AF-388 — validation, query and component improvements

- Changed: Fields explain errors after blur and save validation retains its section links. Hidden input-key normalization accepts ordinary punctuation, numeric starts, accents, long labels and non-ASCII labels; collisions identify the matching input label. Existing saved snapshots remain unchanged.
- Queries: Workflow cards consume a compact, tenant-scoped SQL summary projection. List/history reads occur only in their visible views. Structured scoped keys and a 30-second freshness window support cache reuse; successful saves seed the detail cache from the response, while scoped lists/history and mutation authority/conflict failures invalidate appropriately. Organization switching evicts workflow caches. Server pagination remains 20 by default/100 maximum; the subsequent completion follow-up adds URL page state.
- Components: Cards, list, history, pager, text fields, input editor and save-error presentation have separate feature-local components; the shared section rail still serves editing and saved inspection.
- Verification: Opus’s implementation run recorded 23 passing workflow browser scenarios and a passing walkthrough capture. The parent completed 33 passing API/public-contract tests, API/UI static checks and the migration-head check, and synchronized the documentation. The delegated run and its continuation hit Claude API rate limits before a final opinion; no Opus approval is claimed for these improvements.


### 2026-10-15 — AF-388 — workflow cards and internal input keys

- Changed: Workflow definitions appear as individual responsive cards with outcome descriptions, step/input counts, saved versions and archive status. Cards open the saved definition. Input keys stay internal in editing and saved inspection; label edits still derive them automatically and validation directs users to the label.
- Verification: All 20 workflow browser scenarios pass, including card summaries/navigation and hidden keys with persisted derivation; UI types/lint also pass. No review is requested, per the user’s instruction.


### 2026-10-15 — AF-388 — label-derived input keys

- Changed: Input labels derive read-only keys in the editor (trim, lowercase, whitespace to hyphens). Label changes update the draft key; existing keys remain intact until their label changes. API/UI validation now accepts hyphens alongside existing underscores; uniqueness and length limits remain enforced.
- Verification: Browser regression reproduced the old unchanged key after a label edit. All 29 workflow API tests and 19 workflow browser scenarios pass, as do API lint/format/types and UI types/lint. No additional review is requested, per the user’s instruction.


### 2026-10-15 — AF-388 — manual authoring and Agent tab integration

- Delivered: **Create workflow** → directly enter/edit workflow details, outcome, steps, typed inputs and output descriptions → explicitly save an immutable version. Add/remove/undo the most recent removal/reorder all retain edited fields. A shared numbered step rail and focused panel support both editing and saved inspection; compact Overview/Version history tabs share the divider baseline, and archive uses the actions menu. Creation fills the content width. Validation opens and links invalid sections with one-based field labels, retains edits and blocks invalid client submissions; API errors use the same panel labels. Removal preserves keyboard focus; lost save authority disables edits while retaining draft section navigation.
- Navigation/authority: Workflows is an Agent tab alongside Chat and Memory, governed by `agent.read` independently of `activity.read`. Existing `/workflows` links redirect to `?tab=workflows` and retain the selected definition. Leaving the tab clears the definition query. URL Organization/Agent identity keys embedded state; Organization switching drops unsaved drafts. Header metadata/actions wrap and tabs scroll on narrow screens. Viewers inspect; Editors author through current effective permissions. Query keys and invalidation remain scoped by Organization/Agent.
- Changed: `api/domains/workflows/`, seven additive public authoring/read operations and their operation inventory, and `ui/src/features/workflows/`. Unreleased migration `a38801c6e001` follows `c42e91b7a603`, adds definition/version constraints and immutable-version protection, and preserves existing Agents. Generation-specific code, tests, unreleased table creation and configuration were removed with the scope reduction. Saved definitions/versions are unchanged by that removal.
- Configuration: `WORKFLOW_AUTHORING_ENABLED=false` by default; local ignored configuration explicitly sets it true and the recreated API reports authoring enabled for Archie. `.env.spec`, Helm/Helmfile and [operations](../../guidelines/operations.md#workflow-authoring-wf01) document the gate. No workflow model/provider credentials or runtime image changes are required.
- Verified: API lint/format/types, migration head check, UI types/lint and Helm renders with the installation gate both off/on pass. The final manual-only full suites passed: 4,443 API tests with one existing skip and 718 browser tests; 30 focused API/contract tests also passed. Opus 5.5 round 7 approved with two documentation corrections, now applied. The subsequent direct-editor change has a browser regression that failed on the hidden Workflow name field before the fix; all 18 focused workflow browser tests and UI types/lint pass for the simplified creation flow. Opus 5.5 round 8 approved that final UI change with no blocking or required findings.
- Evidence: Screenshots and recording use the real UI with browser fixture data; the walkthrough records direct manual creation, section editing, removal/undo, saving and immutable version inspection.
- Follow-up: Coordinate the merge; staging has a sibling migration branch and will require `make merge-heads` when integrating there. No version bump, run start, provider effect or unrelated ticket change accompanies WF01.
