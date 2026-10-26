# Sync providers — change log

Status: Active
Epic: AF-383 — Connect an Organization to OneDrive; AF-384 — Two-way file sync; AF-385 — Per-Agent file sync status and switch
Related context: [Sync providers](README.md), [ADR: plugin seam](../../adr/2026-10-16-sync-provider-plugin-seam.md), [ADR: Agent file sync](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md), [Integrations](../integrations.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: the sync provider seam (`api/domains/sync_provider/`). `SyncProviderPlugin`, `SyncProviderPluginRegistry` and `shipped_plugins` are registered in `AppModule`, with OneDrive (`OneDriveSyncProviderPlugin`) as the only shipped provider.
- Delivered: the `sync_provider_connection` table (migration `734b0f2b3793`), keyed by `provider_key`, with statuses `pending`, `active` and `disconnected`. One open connection per Organization across providers; rows cascade on Organization delete.
- Delivered: the provider list `GET /organizations/{organization_id}/sync-providers` (`organization.read`), the provider-keyed connection routes under `…/sync-providers/{provider_key}/connection` (`organization.update`), and the unauthenticated callback `GET /api/v1/integrations/sync-provider/{provider_key}/callback`. The behaviour contract is [`README.md`](README.md).
- Delivered (OneDrive):
  - **Connect:** sign-in at the `organizations` authority, then a site picker. Choosing a site grants the platform app `write` on it and ensures the "Agent Barn" folder as the app; a failure after the grant revokes it.
  - **Disconnect:** revokes the grant with a fresh sign-in from the same tenant. The folder stays.
  - **Approval:** a one-time approval link for a Global Administrator.
- Delivered: the SharePoint guard in both directions:
  - connecting refuses a site any Agent in the Organization (including a deleted one) holds a selected-sites grant on;
  - the SharePoint integration refuses to grant an Agent the folder site.
- Delivered: Settings → **Sync**. One row per offered provider, with Connect, Open and Disconnect by role, the inline picker, Start over, and the server's `blocked_reason`.
- Delivered: the platform app settings `ONEDRIVE_SYNC_CLIENT_ID` / `ONEDRIVE_SYNC_CLIENT_SECRET` and their deploy wiring (chart Secret, Helmfile, `deploy.yml`, `deploy-public.yml`). Unset values render blank, which leaves OneDrive out of the list.
- In transition: no GitHub variable or secret is set yet, so every deployed environment renders the settings blank.
- Next: the manual run against the test tenant with the new redirect URI (acceptance criteria 3 to 6, and disconnect); then close this log.
- Blockers: none. Enabling an environment later needs the GitHub variable and secret, and that environment's `<WEB_APP_URL>/api/v1/integrations/sync-provider/onedrive/callback` registered on the Microsoft app.

Acceptance criteria amendment: the ticket orders the flow "Microsoft admin consent → Microsoft sign-in". Starting every connect at admin consent shows "Need admin approval" to anyone who isn't a Global Administrator, even after their organization approved the app (seen in the 2026-10-14 verification). So connecting starts at sign-in, and admin consent is a one-time step per organization via `approval_url`. There is still no second consent prompt, and the tenant still comes from `tid`.

Acceptance criteria amendment: another Organization's caller gets **403**, not 404. `get_current_user()` refuses a caller outside the path Organization before any route runs, as for every Organization-scoped resource; 404 concealment applies to Agent resources only ([RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md)).

Scope change (maintainer, 2026-10-16): OneDrive became the first provider of a generic sync provider seam, so Dropbox and Google Drive can be added as plugins; an Organization connects one provider at a time. See the [ADR](../../adr/2026-10-16-sync-provider-plugin-seam.md).

### AF-384 — Two-way file sync

- Delivered:
  - Microsoft and runtime image verification (no code);
  - the [Agent file sync ADR](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md), with `CONTEXT.md` defining Agent Folder, File Sync and Sync Category;
  - the sync rules (`api/domains/file_sync/rules.py`);
  - the file sync tables (migration `af95cf4c3a1e`);
  - the Graph file operations (`api/domains/agents/microsoft_graph_files.py`) and the app-token cache.
  - the `file_sync` capability on the plugin seam, implemented by OneDrive, and a test-only `file_sync` provider;
  - folder reconciliation (`FileSyncEngine.reconcile_folders`);
  - the Sync Engine (`api/sync_engine_main.py`) and its deployment: Helm `syncEngine`, `make dev-sync-engine`, and the `sync-engine` Compose service started by `run.sh`;
  - the pod's file report route (`POST …/file-sync/changes`): authentication, readiness checks and path rules; upload links, empty files, skips, and deletes for a complete report. Upload completion is at `POST …/file-sync/uploads/complete`;
  - the pod's jobs (`GET …/file-sync/operations`, `POST …/file-sync/operations/result`): downloads and re-uploads with leases, retries and the Agent-wins conflict rule;
  - remote changes:
    - people's content edits become downloads (work, memory) or undos (config, skills);
    - added files are parked in `_Not synced/`;
    - deleted or moved-away files are restored, and renamed ones are moved back;
    - Agent folders are put back or re-created;
    - an expired cursor triggers a full re-listing.

  Folders follow Agents on every connected Organization. No pod calls these routes yet, so files are not synced.
- Next, in this order, each as its own slice. Each slice adds the repository queries it uses.
  1. the in-pod helper;
  2. builder and `start.sh` wiring;
  3. pinned-image contracts;
  4. disconnect;
  5. docs consolidation;
  6. an end-to-end run on local k3d against the test tenant.
- Docs owed by the slice that makes them true:
  - **this README:**
    - the Organization Member visibility limit, with the helper wiring;
    - the disconnect section, with disconnect;
  - **RBAC brief:** the visibility limit;
  - **[Agents](../agents.md):** delete stops sync, and a restore is followed on the next start;
  - **[activity and ingest](../activity-and-ingest.md):** each new route as it lands;
  - **[runtime and deployment](../../architecture/runtime-and-deployment.md):** the new start step;
  - **[INDEX](../../INDEX.md):** the helper.
- Blockers: none.

Acceptance criteria amendments (maintainer, 2026-10-21; see the ADR):
- **Tables:** three generic tables (`sync_agent_folder`, `sync_file`, `sync_activity`) instead of the ticket's four `onedrive_*` ones. Pending uploads and pod work are columns on `sync_file`, not tables of their own. The in-pod helper is `file-sync.py`, not `onedrive-sync.py`.
- **Never in the provider:** "No path from `HERMES_EXCLUDED` / `OPENCLAW_EXCLUDED` ever appears" applies to credentials and runtime machinery. Template-rebuilt files (`SOUL.md`, `AGENTS.md`, `IDENTITY.md`, `TOOLS.md`, `BOOT.md`, `HEARTBEAT.md`, `BOOTSTRAP.md`) and `skills/` are mirrored read-only, with edits undone.
- **Conflicts:** the user's version stays in the provider's version history. No `name (your edit YYYY-MM-DD).ext` copy is made. This also applies after an Agent Restore Point restore.
- **Folders:** created, renamed and stopped by the Sync Engine's pass, not by an event handler for `agent.created`/`agent.updated`/`agent.deleted`. No new RBAC background-work exception is needed.
- **Disallowed changes while stopped:** undos, restores of deleted files and re-uploads wait for the Agent's next start. "Within 2 minutes" applies to running Agents.
- **Agent deletes:** an Agent deleting a file deletes it at the provider (recycle bin).
- **Disconnect:** deletes the Agent folders and keeps the "Agent Barn" root.
- **Accepted limit:** every Organization Member can read the Agent Folders, and edit work and memory files, at the provider.
- **End-to-end run:** on local k3d against the test tenant instead of staging.
- **Activity:** stored only. Its route and UI belong to the next ticket.

### AF-385 — Per-Agent file sync status and switch

- Delivered:
  - the schema: `agent.file_sync_enabled` (on by default) and `sync_agent_folder.resync_requested_at` (migration `df10528f512f`);
  - `POST …/agents` accepts `file_sync_enabled` and stores it;
  - the Domain Events `agent.file_sync.enabled` / `agent.file_sync.disabled`, registered for the security audit;
  - `PUT …/agents/{agent_id}/file-sync` (`agent.update`): sets the switch, makes the Agent's folder `disabled` or `active` with a re-check requested, and records the event, in one transaction. A folder that is turned off is already refused by Ingest and left alone by the Sync Engine.
- In transition:
  - an Agent switched off before it has a folder still gets one when the engine reaches it, and Ingest doesn't read the switch itself;
  - `resync_requested_at` is written but not yet read, so turning on resumes the folder without the re-check.
- Next, in this order, each as its own slice:
  1. Ingest refusing a switched-off Agent;
  2. the engine applying the switch to folders;
  3. making the full re-list safe alongside the pod;
  4. turning on re-checks the folder;
  5. `GET …/file-sync` (status) and `GET …/file-sync/activity`;
  6. the Agent page File sync tab (status and switch, then activity);
  7. the hire form option;
  8. the local k3d end-to-end run;
  9. closing this log.
- Blockers: none.

Acceptance criteria amendments (maintainer, 2026-10-23):
- **Names:** routes under `/organizations/{organization_id}/agents/{agent_id}/file-sync` and the UI folder `ui/src/features/file-sync/`, not `onedrive-sync`. Every provider word comes from the provider, as everywhere else in the seam.
- **Routes:** status (`GET …/file-sync`) and history (`GET …/file-sync/activity`) are separate reads. `PUT …/file-sync` returns `{agent_id, enabled}`, so a caller without `activity.read` never receives the status.
- **The switch:** it is stored on the Agent, can be changed at any time (including before the folder exists or while not connected), and is offered when creating an Agent. An Agent created with sync off gets no folder.
- **Turning on:** the Sync Engine re-checks the folder, so edits, deletions and new files made at the provider while sync was off are handled.
- **"Conflict copies":** the activity is `conflict_agent_won`; AF-384 keeps the person's edit in version history instead of making a copy.
- **States:** a transient "Setting up the folder…" state is added to the ticket's five.
- **The tab:** the card is on a new File sync tab, gated on `activity.read`. All ten activity kinds are listed.
- **Manual check:** on local k3d against the test tenant, not on staging.

## Changes

### 2026-10-26 — AF-385 — Turning sync off or on

- Delivered: `PUT /organizations/{organization_id}/agents/{agent_id}/file-sync {enabled}` → 200 `{agent_id, enabled}`.
  - **Permission:** `agent.update` (`AgentAuthorization.require_action`). An invisible, other-Organization or deleted Agent is 404; a visible one without the permission (Agent Viewer) is 403; a read-only API key is 403.
  - **One transaction** (`AgentFileSyncRepository.set_enabled_with_event`): locks the Agent row, sets `file_sync_enabled`, updates the Agent's folder on the active connection (off: `disabled`; on: `active` with `resync_requested_at`), and stages the Domain Event. Deliveries are enqueued after commit.
  - **No change, no record:** setting the current value returns 200 and writes nothing.
  - **Payload:** `AgentFileSyncUpdate` refuses a missing or non-boolean `enabled` and any other field (422).
- Changed:
  - `AgentFileSyncRepository` is a new repository for the user-facing request, separate from the Sync Engine's `FileSyncRepository`, so the RBAC background-work exception keeps covering only engine work.
  - `api/developer_docs/operations-v1.json` lists the operation.
  - **One file pair per app**, as Agent Memory (`gateway_routes.py`/`gateway_service.py`) and Workflows (`runtime_routes.py`/`runtime_service.py`) do: the pod-facing Ingest router, `FileSyncIngestService`, its exceptions and `FileSyncTarget` moved unchanged from `routes.py`/`service.py` to `ingest_routes.py`/`ingest_service.py`, which only `ingest_app.py` imports. `routes.py`/`service.py` now hold the product API: the switch, and `FileSyncFolderRemoval` for disconnect. The moved code is byte-identical to the previous commit.
  - README: new "Turning sync off" section. RBAC brief: the request and its repository. `CONTEXT.md`: File Sync names the switch.
- Verified:
  - **`tests/integration/test_file_sync_switch.py` (21 tests, product API with Test Drive).** 16 failed first, all with 404 because the route didn't exist. The 5 that passed before did so for that same reason: a Member without access (404), the three absent, deleted and foreign Agents (404), and one Agent's switch leaving another Agent alone. They are guards now that the route exists.
  - They cover Owner, Admin, Agent Owner, Editor and Viewer; a Member without access; missing, deleted and foreign Agents; a read-only key; no authentication; three malformed bodies; the folder disabled and kept at the provider; the folder resumed with a re-check requested; no folder; both events in order and their payload; a repeated value recording nothing; another Agent left alone.
  - **Regression:** `test_agent_memory.py` and `test_file_sync_ingest_auth.py` pass (78). After the move, the three Ingest suites, `test_file_sync_disconnect.py`, `test_file_sync_switch.py` and `test_public_api_contract.py` pass together (100). The API, Ingest and Sync Engine apps import.
  - ruff, format and ty pass (ty apart from the 11 existing Unix-only diagnostics).

### 2026-10-26 — AF-385 — Domain Events for the switch

- Delivered: `AGENT_FILE_SYNC_ENABLED` (`agent.file_sync.enabled`) and `AGENT_FILE_SYNC_DISABLED` (`agent.file_sync.disabled`), schema version 1.
  - **Payload:** `AgentFileSyncChangedPayload`: Organization and Agent ids, actor and Agent display names, nothing else (`extra="forbid"`).
  - **Handler:** routed to `security_audit.projection` only, which lists them as supported. They stay out of product analytics, like the Agent Memory switch.
- Changed: [Domain Events](../domain-events.md) names the two events.
- Verified:
  - **6 new tests, all failing first:**
    - `test_domain_events.py`: for both events, the payload carries only the four fields (failed on the event not being registered), and any other field is refused (failed because the error was `UnsupportedDomainEventError`, not a payload refusal).
    - `test_event_handler_registry_wiring.py`: both route to the security audit only, and the production handler registry supports them (failed: no handlers).
    The tests name the events by string, so they fail on an assertion rather than on an import.
  - Both unit files pass (49 tests). ruff, format and ty pass (ty apart from the 11 existing Unix-only diagnostics).

### 2026-10-26 — AF-385 — Creating an Agent with sync off

- Delivered: `AgentCreate.file_sync_enabled` (default `true`), stored by `create_agent`. Unknown fields are still refused (422).
- In transition: the engine doesn't read the switch yet, so an Agent created with it off still gets a folder; the engine slice makes the switch take effect.
- Changed: [Agents](../agents.md) "Create" names the field.
- Verified:
  - **2 new tests in `test_agents.py`:** creating with `file_sync_enabled: false` stores false, and it failed first (422, field refused). Creating without it stores true; it passed before and after, because the column already defaults to true. It is a guard.
  - **The create tests:** `test_agents.py -k create_agent` and all of `test_onboarding.py`, which builds the only other `AgentCreate`, pass (66).
  - ruff and format pass. ty passes apart from the 11 existing Unix-only diagnostics.

### 2026-10-26 — AF-385 — Switch and re-check columns

- Delivered: migration `df10528f512f` (revises `af95cf4c3a1e`):
  - `agent.file_sync_enabled`, Boolean, not null, server default `true`, so existing Agents keep syncing;
  - `sync_agent_folder.resync_requested_at`, timestamptz, nullable.

  The models gain `Agent.file_sync_enabled` and `SyncAgentFolder.resync_requested_at`.
- Verified:
  - **New tests, all 3 failing first** at their column assertions (column missing):
    - `test_file_sync_schema.py`: a folder starts with no re-check requested; a new Agent syncs its files;
    - `test_rbac_schema.py`: existing Agents keep syncing after the upgrade. It sits beside the Agent Memory column test, because that file's `legacy_database` fixture is the one that upgrades a database with existing Agents.
  - **Both files pass** (45 tests).
  - **Checks:** one Alembic head (`df10528f512f`), ruff and format pass. ty passes apart from the 11 existing Unix-only diagnostics (`os.getuid` and similar in runtime and test fixtures), run with `--python .venv/Scripts/python.exe` on Windows.
- Not verified: the downgrade path was not run.

### 2026-10-23 — AF-384 — Activity notes carry the time the change really happened

- **Problem:** `edit_undone` and `restored` were recorded when the engine noticed a person's edit or delete. For a stopped Agent, the Agent's copy is only put back at its next start, so the note claimed it happened days early. If the job was dropped (the Agent had deleted the file too), the note described something that never happened.
- **Delivered:**
  - **Owed note:** `sync_file.pending_activity`, a nullable `String(32)` added to the existing AF-384 migration `af95cf4c3a1e` at the maintainer's request, not a new migration. The engine now stores the owed note instead of writing it: `mark_remote_change(…, note=EDIT_UNDONE)` for a locked file's edit, and `restore_from_agent` sets `RESTORED`.
  - **Written on completion:** `uploads/complete` writes the owed note with the completion time.
  - **Cleared when the job ends:** `record_synced`, `clear_pending` and `adopt_item` clear it. A dropped job never writes its note.
  - **Unchanged:** `folder_restored` is still written at once, because the engine rebuilds folders itself.
  - **Behaviour change:** several edits to a locked file before the undo make one `edit_undone`, for the one undo. It used to be one per provider version.
- **Migration:** a database that already ran `af95cf4c3a1e` lacks the column, so start from a fresh database. The branch is unreleased.
- **Verified:**
  - **3 new tests:** a note is written at completion (`occurred_at` at or after the moment before completion), a restore note is written at completion, and no note is written when the Agent deleted the file too.
  - **6 existing assertions** now check "no note yet, one owed".
  - **2 tests** that counted notes at detection now check one owed undo, and a second pass leaving the job's wait untouched.
  - **Order:** the 9 changed or new tests failed first. The 2 counting tests broke with the fix and were then rewritten.
  - **Suites:** the sync provider and file sync suites pass together (387, with `TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1`).
  - **Checks:** `make check-migrations`, ruff, format and ty pass.

### 2026-10-23 — AF-384 — Retiring an Agent deletes its folder

- **Decision (maintainer, 2026-10-22, during the end-to-end run):** retiring an Agent deletes its Agent Folder at the provider. It used to be marked `stopped` and kept. Stopping an Agent never touches its folder.
- **Delivered:**
  - **Rename:** the folder state set on retire is renamed from `stopped` to `retired` (`SyncFolderStatus.RETIRED`, `FileSyncRepository.retire_folders`), so it no longer reads like a stopped, restartable Agent. No migration changes: the column is plain `String(16)` with no allowed-value list.
  - **`reconcile_folders`:** marks each folder of a retired Agent `retired`, then deletes it through the new `delete_agent_folder` (provider `delete_item`, `RemoteItemMissing` ignored, then `remove_folder`). This runs before names are given out.
  - **Failures:** throttling propagates, so `run_pass` postpones the connection by `Retry-After`. Any other provider failure is logged, and that folder is retried on the next pass.
  - **Disconnect:** `FileSyncFolderRemoval.remove_agent_folders` uses the same function.
  - **UI:** the retire dialog adds "Its folder in {provider} is deleted too." when the Organization has an active provider with `file_sync` (`useSyncProvidersQuery`).
- **Verified:**
  - **`test_file_sync_folders.py` (30 tests):**
    - 2 rewritten (retiring deletes the folder; a new Agent named like a retired one gets the plain name) and 5 added (already gone, throttled then retried, another failure not holding up other Agents, a disabled folder, the change feed reporting the deletion rebuilding nothing), all 7 failing first;
    - 1 guard added: stopping an Agent keeps its folder `active`.
  - **Disconnect test:** `test_file_sync_disconnect.py`'s first test relied on a retired folder outliving the engine pass. It now marks the folder `retired` directly, so it still proves disconnect removes a folder whose deletion is pending.
  - **Suites:** the sync provider and file sync suites pass together (384 tests, run with `TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1`).
  - **UI:** `agent-configuration-page.spec.ts` and `sync-provider.spec.ts` pass (66). The provider sentence test failed first; the no-provider test is a guard.
  - **Checks:** `pnpm lint`, `tsc --noEmit`, ruff, format and ty pass.
- **End-to-end on local k3d:** pending the maintainer's deploy.

### 2026-10-22 — AF-384 — Docs consolidation

- **README "Agent file sync":**
  - **Intro:** describes the delivered design instead of "delivery is in progress".
  - **New sections:**
    - "What syncs": the categories per runtime, from `rules.py`;
    - "How fast changes travel": 15 s helper rounds with a 5 s settle; at most about 75 s for a person's change (30 s engine pass, 30 s autosave wait, 15 s helper round); a stopped Agent's jobs applied before its runtime starts;
    - "The Agent's own changes", which links to the Ingest contract instead of repeating it;
    - "Activity": the ten kinds;
    - "Limits";
    - "Known limits of file sync". The "Agent Barn" root deletion moved here from "People's edits", next to the Member visibility limit, stopped Agents, conflicts, running Agents and pods polling without a connection.
  - **Source map:** now has the Ingest service and routes, the pod helper with its builders and `start.sh`, the helper unit tests and the pinned-image contracts. The Role section names `microsoft_graph_files.py`.
- **RBAC brief:** now records the accepted Member visibility gap at the provider. It was planned for the first slice and had been recorded only in the ADR.
- **`CONTEXT.md`:** Agent Folder says disconnecting deletes every Agent Folder.
- **INDEX:** the sync provider row's label names Agent file sync's topics.
- **Verified:**
  - a link check over every Markdown file AF-384 touched: each relative link's file, each `#anchor` (GitHub slugs) and each backticked `../` path in tables resolves. The checker was proven against a sample with a broken file, anchor and path;
  - the README's claims were checked against the code: OpenClaw keeps only `USER.md` (memory) across starts, so `config` files are rebuilt every start, and both the engine and Ingest record `skipped_too_large`.

### 2026-10-22 — AF-384 — Disconnect removes the Agent folders

- **Delivered:** after the sign-in and same-account checks, `SyncProviderService.disconnect` holds the connection's Sync Engine lock through `FileSyncFolderRemoval.holding`.
  - **Lock:** `FileSyncRepository.connection_lock` gains `wait_seconds` and polls every 0.1 s. Disconnect waits up to 15 s (`DISCONNECT_LOCK_WAIT_SECONDS`); if the lock isn't free by then, it answers 409 and changes nothing.
  - **Order:**
    1. every Agent Folder is deleted at the provider with Agent Barn's own access (`delete_item`), and its row removed (`remove_folder`). `sync_file` rows cascade, and `sync_activity` keeps its history with `folder_id` cleared. A folder already gone (`RemoteItemMissing`) is skipped.
    2. the grant is revoked.
    3. the connection is marked disconnected.
  - **On failure:** a provider failure leaves the connection active, and the next engine pass gives every Agent without a folder a new one.
- **Changed:**
  - `FOLDER_NAME` moved from `sync_provider/service.py` to `sync_provider/models.py`. The engine imported it from the service, which made the service's new import of `file_sync.service` circular.
  - The ADR's disconnect line now says the folders are deleted with Agent Barn's own access, as the PR 5a amendment decided.
- **UI:** the disconnect dialog's wording follows the provider's `file_sync` capability. The e2e OneDrive fixture now lists `file_sync`, as the API has since the OneDrive plugin declared it.
- **Verified:**
  - **`tests/integration/test_file_sync_disconnect.py` (7 tests), through the real route with Test Drive:**
    - deletes before the revoke, the root kept, rows removed, activity kept, no Kubernetes call;
    - no folders after a later engine pass;
    - an already-gone folder is skipped;
    - a failure on the second folder leaves the connection active, and the engine rebuilds the folder;
    - a failed revoke leaves the connection active, and the folders are rebuilt;
    - a held lock gives 409 with nothing changed;
    - disconnect waits for a running pass.

    6 failed first. The failed-revoke test passed before and after, because nothing was deleted before.
  - **Other checks:**
    - the sync provider and file sync suites pass together (378 tests);
    - all 24 tests in `ui/tests/e2e/sync-provider.spec.ts` pass. The OneDrive wording test failed first; the test for a provider without file sync is a guard;
    - `pnpm lint`, `tsc --noEmit`, ruff, format and ty pass.

### 2026-10-22 — AF-384 — Pinned-image file sync contracts

- **Delivered:** `api/runtime_tests/test_{hermes,openclaw}_file_sync.py` over the shared `file_sync_contract.py`.
  - **Setup:**
    - each runs the real `start.sh` from the generated ConfigMap in the pinned image with `--network=none`;
    - a loopback ingest stub (`runtime_tests/fixtures/file_sync_ingest_stub.py`) logs requests to a mounted folder;
    - a probe replaces `hermes` / `openclaw gateway` and records how many requests had arrived when the runtime started.
  - **Checks:**
    - the first round (report, uploads, confirmations, jobs) finishes before the runtime starts;
    - the report is complete and offers the Template files, the skill and native memory;
    - no path the rules never sync is offered, and planted `config.yaml` / `openclaw.json` / `.env` / `aai-cli/key` are absent;
    - uploads carry no `Authorization` and match the reported hashes;
    - the runtime still starts when ingest cannot be reached.
- **Fixed:** the helper's `--once` run reported nothing at start.
  - **Cause:** `start.sh` writes the Template files and skills moments before it, and the 5-second settle rule treated all of them as still being written. The real image showed an empty report with `complete: false`.
  - **Fix:** `--once` now scans without the settle wait, since the runtime has not started. The background loop keeps it.
  - **Tests:** a new `test_file_sync_helper.py` test failed first. The two settle tests now run one loop round instead of `--once`.
- **Verified:**
  - the 4 contracts pass against `k3d-registry:5000/agentfarm-{hermes,openclaw}-base:dev` (Python 3.13.5 and 3.12.13) and against `hermes-base:local` / `openclaw-base:local`;
  - the helper suite has 25 passing and 2 skipped on Windows;
  - ruff, format and ty pass.
- **Noted:** generated files are written with `newline="\n"`, so the contracts also run from Windows.

### 2026-10-22 — AF-384 — Builders and start.sh run the pod helper

- **Delivered:**
  - **ConfigMaps:** both carry `file-sync.py` and `file-sync-rules.json` (`rules_manifest` for that runtime). For OpenClaw they sit beside the other start scripts.
  - **start.sh:**
    - Hermes runs `file-sync.py --once || true` after the Template files and skills are written.
    - OpenClaw runs it after `init-openclaw.js`, the aai-cli and gog setup, and the memory gateway wait.
    - Both then start it in the background before the ready file is touched.
  - **Hermes path:** `/workspace` is the PVC's `workspace` subPath, so the rules' `/opt/data/workspace` is the same files.
  - **CI:** `ci.yml` runs both runtime workflows when `scripts/file-sync.py` or `file_sync/rules.py` change.
  - **Runtime digest:** the builders call `rules_manifest`, so the rules module is part of the digest, and so is the script. Running Agents show an update and start syncing after their next restart or managed update.
- **Docs:**
  - the README "The Agent's pod" section;
  - the runtime-and-deployment start-up paragraph.
- **Verified:**
  - **Builder and digest tests:** 2 builder tests per runtime (ConfigMap contents and start order) and 1 digest closure test failed first. The asset-name assertion passed before, because the script already existed.
  - **`test_file_sync_pod_secrets.py`:** starts an OpenClaw and a Hermes Agent through the API while a OneDrive connection is active and `MicrosoftAppTokens` holds an app token. Nothing sent to Kubernetes contains the token or the client secret. It failed first only on its check that the ConfigMap carries the helper; the credential check is a guard.
  - **Targeted suites:**
    - the builder, start, ConfigMap contract, digest, file sync helper and Agent start suites pass;
    - **failing on this Windows machine with or without this change:**
      - the symlink tests in `test_restore_point_job.py` (WinError 1314);
      - two `test_agents.py` concurrency tests (they also fail with this slice's code stashed);
      - two `test_sharepoint_agent_start.py` tests, because the local `.env` sets `INGEST_BASE_URL`.
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Pod helper: downloads and re-uploads

- **Delivered:** after each report and its uploads, `file-sync.py` claims its jobs (`GET …/file-sync/operations`) and applies them.
  - **Downloads:**
    - A download is applied only over the exact content the pod reported in the same round. A file that is missing, still being written, or changed at any point before `os.replace` is answered `local_changed`, so the Agent wins.
    - Free space is checked against the download's `Content-Length`. If there isn't enough room, or the disk fills while writing, the answer is `skipped_no_space`.
    - The file is written to a `.file-sync-` temp file in the same directory, flushed to disk, given the old file's permissions, then swapped in with `os.replace`. The temp file is always removed when the download doesn't finish.
    - `done` reports the job's version and the written hash and size, and updates the scan cache, so the next report carries the new content even inside the 5-second settle window. Without that, the old content would be uploaded back.
    - A provider error, or a job without a version, is answered `failed`.
  - **Re-uploads:** the Agent's copy is sent through the job's upload link and finished with `uploads/complete`. A file the pod didn't report, or that changed since, is answered `failed`.
  - A job for a path outside the sync rules is ignored. The pod never deletes a file.
- **Verified:**
  - `tests/unit/test_file_sync_helper.py` now has 26 tests. The fake ingest checks handed-out jobs with `FileSyncOperationsRead` and results with `FileSyncOperationResultCreate`, and refuses an `Authorization` header on download links.
  - The 8 new job tests failed first. The guard that jobs never remove or change another file passed before and after. The permission test is skipped on Windows and runs on Linux.
  - `test_agent_runtime_digest.py` passes.
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Pod helper: scan, report and upload

- **Delivered:** `api/domains/agents/scripts/file-sync.py`, stdlib only and pinned to Python 3.12 for ruff in `pyproject.toml`. Nothing starts it yet; the builders and `start.sh` come in a later slice.
  - It reads `AGENT_ID`, `INGEST_URL` and `INGEST_API_KEY`, the rules JSON produced by `rules_manifest` (`FILE_SYNC_RULES`, default `/app/config/file-sync-rules.json`), and a scan cache in `/tmp` (`FILE_SYNC_STATE`), never on the volume.
  - **Scan:**
    - it decides the same as the server's `classify` (parity test for both runtimes);
    - it enters only directories that can hold synced files;
    - it skips symlinks, the skip directories, `_Not synced`, non-NFC names, paths over 1,024 characters and `.file-sync-` temp files;
    - hashes are cached by size and modification time.
  - **Files still being written** (changed within the last 5 seconds, or during hashing) keep their last reported version. If there is none, the file is left out and the report is marked incomplete, so nothing is deleted at the provider. Read errors or more than 10,000 files also mark the report incomplete.
  - **Uploads:**
    - for each upload link, the file is re-hashed first and left alone if it changed;
    - it is sent in 10 MiB chunks (a multiple of 320 KiB) with `Content-Range`;
    - `uploads/complete` is called only when the bytes sent match the reported hash.
  - **Responses:**
    - a 401 stops the helper quietly;
    - a 429 or 503 with `Retry-After` waits that long;
    - other failures wait for the interval.
  - **Network:** ingest calls bypass proxies, like the other pod scripts. Upload links are never logged.
  - **`--once --timeout N`** (default 60) always exits 0 within the timeout. **Loop mode** uses `--interval` (default 15).
  - The helper never deletes or changes a file on the volume.
- **Verified:**
  - `tests/unit/test_file_sync_helper.py` (16 tests) runs the script as a subprocess against a real local HTTP server that checks every body with the ingest Pydantic models, and loads it with `importlib` for chunking and classify parity. Before the script existed, the run stopped at the first test, which failed.
  - The symlink test is skipped on Windows and runs on Linux.
  - `test_agent_runtime_digest.py` still passes.
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Change feed robustness: expired cursor, throttling, stopped Agents

- Delivered: when the provider reports the stored cursor as no longer valid (`RemoteResyncRequired`), `process_changes` re-lists everything under "Agent Barn" from the start (`changes(root, None, from_start=True)`, every page) and passes each item through the normal change handling. Recorded content versions mean unchanged files create no jobs and no activity. Afterwards:
  - every active Agent folder that was not listed is rebuilt (`_rebuild_folder`, shared with the folder-change handling);
  - every synced file that was not listed, in a folder that was, is restored from the Agent;
  - the listing's final cursor is saved, only at the end, so an interrupted re-listing starts again.
- **Verified rather than built:**
  - throttling while reading changes pauses only that connection by the provider's `Retry-After` and keeps the cursor, and the next due pass handles the change;
  - a page interrupted by throttling mid-way is read again with nothing done twice (no double parking, moves or activity);
  - a stopped Agent's jobs wait and are handed out to its pod later.
- Delivered: `FileSyncRepository.synced_files_in_connection`.
- **Known limit, unchanged:** deleting the "Agent Barn" root is not handled.
- Fixed (tests):
  - **Expired cursors:** Test Drive treated a cursor issued just after `expire_cursors` as expired too, which would have made the engine re-list forever. Expiry now invalidates only earlier cursors. A new contract test failed before the fix.
  - **`throttle_call(name, retry_after)`:** new in Test Drive, so a test can throttle one kind of call, with its own contract test.
- Verified:
  - `tests/integration/test_file_sync_remote_resync.py` (10 tests). The 7 for re-listing failed first. The 3 behaviour proofs (throttling while reading changes, an interrupted page, a stopped Agent) passed before and after.
  - The fake's fix was found by the first green run: 9 of 10 passed, and the remaining failure was the fake's cursor.
  - All file sync suites pass together twice (168 tests).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — People adding, moving and deleting files and Agent folders

- Changed: `FileSyncEngine._remote_change` now handles every non-app change. Items the provider attributes to an app are skipped first, which covers the engine's own moves and renames.
- **Files:**
  - **Matching:** a synced file is found by item id across the whole connection, so moves between Agent folders are seen.
  - **Deleted, or moved out of "Agent Barn", into `_Not synced/` or into another Agent's folder:** restored by a `reupload` job (`restore_from_agent` clears the provider fields), with `restored` recorded. A file landing in another Agent's folder is parked in that folder's `_Not synced/`.
  - **Renamed or moved within its own folder:** moved back with `move_item` to its original parent and name, with `renamed_back` recorded. When the way back is missing or taken, the original is restored and the moved copy parked instead.
  - **New file with no row:** moved into `<Agent>/_Not synced/`, created when missing, with ` (2)`, ` (3)` before the extension on a name clash, and `moved_not_synced` recorded. Items inside `_Not synced/` are never touched.
  - **New item at a synced path:** adopted as that row's item (`adopt_item`) and handled as a content edit, unless the Agent's own upload of that path is under way.
- **Agent folders:** a folder found by its item id that was renamed or moved is moved back under the root with its name. A deleted folder, or one that cannot be moved back, has its item id cleared, so the next pass creates it again, and all its files get `reupload` jobs (`restore_folder_files`). Each records `folder_restored`.
- Removed: `FileSyncRepository.file_by_item`, replaced by `file_by_item_in_connection`. Added: `restore_from_agent`, `restore_folder_files`, `adopt_item` and `forget_folder_item`. `record_activity` accepts no path.
- **Known limit:** deleting the "Agent Barn" root is not handled; the change feed is anchored to it.
- Fixed (tests):
  - **Deletions:** Test Drive reported a person's deletion as made by the app. PR 0 showed deleted items carry no modifier, so the fake now reports none, and its contract test checks this; it failed before the fix.
  - **Moves out of "Agent Barn":** Test Drive did not report a file moved out of "Agent Barn" at all; its change feed now reports it as deleted. What the provider really reports is added to the end-to-end checks.
  - **`upload_through_the_pod`:** it reported its single file as a complete list, so a second upload in one test deleted the first at the provider. It now reports an incomplete list.
- Verified:
  - `tests/integration/test_file_sync_remote_moves.py` (15 tests). 12 failed first. The three "nothing happens" guards passed before and after: inside `_Not synced/`, an upload under way, and the engine's own moves.
  - All file sync suites pass together twice (156 tests).
  - ruff, format and ty pass.
- Follow-up, for the end-to-end run:
  - what the provider's change feed reports for an item moved out of the watched folder, and for a deleted folder's children;
  - deleting the "Agent Barn" root.

### 2026-10-22 — AF-384 — People's edits become downloads or undos

- Delivered: `FileSyncEngine.process_changes(connection)`, run by every engine pass after the folders.
  - **No cursor yet:** it stores a cursor starting now (`changes(root, None)`) and processes nothing.
  - **Otherwise:** it reads every page since `sync_cursor` and saves the new cursor after each page.
- **Matching a changed item:**
  - its folder by the path's first segment, among active folders that exist at the provider;
  - its `sync_file` row by item id, with the same path, case-insensitively.
- **Ignored:**
  - folders, deleted items, and items without a path, folder or row (new, renamed and moved files come in the next slice);
  - changes the provider attributes to an app (`modified_by_app`);
  - files with an upload under way;
  - an unchanged `content_version`.
- **A person's content edit:**
  - **Work and memory:** `pending = download`. Over 100 MB, `skipped_too_large` is recorded once per version and nothing is downloaded.
  - **Config and skills:** `pending = reupload`, with `edit_undone` recorded once per provider version.
  - **Not before:** `retry_at` is the item's last modification plus 30 s (the PR 0 autosave finding). The pod's job claim already waits for `retry_at`, so each autosave pushes the job back without holding the cursor.
  - **One action per file:** a pending action is only refreshed by the same action (`mark_remote_change`), so an undo is never turned into a download.
- Delivered: `FileSyncRepository.save_cursor`, `folders_with_runtime`, `file_by_item` and `mark_remote_change`.
- Changed:
  - Sync provider README: the "People's edits" section. The folder note "a pass with nothing to do makes no provider call" is corrected to cover the folder part only, because every pass now reads the change feed.
  - `file_sync_ingest_base(clean_database=True)` cleans the database before the Organization is created.
- Verified:
  - `tests/integration/test_file_sync_remote_edits.py` (14 tests) failed first. The first run failed in setup, because the database was cleaned after the Organization was made. After that was fixed, all 14 failed on the missing `process_changes`; they now pass.
  - They cover:
    - the cursor starting now;
    - the Agent's own uploads ignored;
    - work and memory edits becoming downloads after 30 s;
    - config and skill edits undone and recorded;
    - repeated edits;
    - an undo not replaced;
    - an upload under way;
    - an edit over 100 MB;
    - a disabled folder;
    - the cursor moving on;
    - a full `run_pass`.
  - All file sync suites pass together twice (141 tests). ruff, format and ty pass.

### 2026-10-22 — AF-384 — Pod jobs: downloads, re-uploads and the Agent-wins rule

- Delivered: `GET /ingest/v1/agents/{agent_id}/file-sync/operations`.
  - It claims the folder's due `sync_file` jobs (`pending` set, no live `lease_until`, no future `retry_at`) with `SELECT … FOR UPDATE SKIP LOCKED`, leases them for 10 minutes, and counts `attempts`.
  - **`download`:** the provider's current `content_version` and a download URL. If the item is gone, or no item was ever recorded, the job is dropped.
  - **`reupload`:** an upload URL, with the row marked under way. The existing `uploads/complete` finishes it.
  - If the provider fails while jobs are being handed out, every claimed job is released.
- Delivered: `POST …/file-sync/operations/result {path, outcome, version?, sha256?, size?}`. It needs a leased job at that path (otherwise 409); `done` without `version`, `sha256` and `size` is 422.
  - **`done`:** the item is read again. With an unchanged `content_version` it is recorded as synced. If the version has moved on, the download is queued again; if the item is gone, the job is dropped.
  - **`skipped_no_space`:** recorded once per path and version, and retried in 5 minutes.
  - **`failed`:** retried after `60 × 2^(attempts-1)` seconds, at most 30 minutes.
  - **`local_changed`:** the job is dropped and `conflict_agent_won` recorded.
- Delivered: a report bringing new local content for a path with a pending download clears the download, records `conflict_agent_won`, and uploads the Agent's version. Unchanged local content leaves the download pending.
- Changed:
  - `record_synced` also clears `pending`, the lease, `attempts` and `retry_at`;
  - `FileSyncRepository` gains `claim_operations`, `clear_pending`, `release` and `requeue_download`;
  - the report tests' helpers moved to `api/tests/steps/file_sync_ingest.py`, the third file to need them.
- Verified:
  - `tests/integration/test_file_sync_ingest_operations.py` (18 tests). 17 failed first. The guard that a report with unchanged content leaves a download pending passed before and after.
  - They cover:
    - the download hand-out;
    - leases and their expiry;
    - `retry_at`;
    - `done`, and `done` overtaken by another edit;
    - no space recorded once;
    - four retry waits;
    - `local_changed`;
    - both report conflict cases;
    - a re-upload finished by upload completion;
    - a gone item;
    - results without a job;
    - key, path and outcome validation;
    - response fields.
  - The file sync, schema and Ingest suites pass together (178 tests).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Files the Agent deleted are deleted at the provider

- Delivered: when a report is `complete`, every known `sync_file` whose path (case-insensitively) is not in the report is handled as follows:
  - **Synced:** deleted at the provider with `delete_item` (recycle bin; an item already gone is not an error), its row removed, and `deleted_by_agent` recorded with the path.
  - **First upload never finished:** the row is removed without calling the provider.
- **Never deleted:**
  - anything, by a report that is not `complete`;
  - a path still in the report, even when it is skipped (for example, now over 100 MB);
  - a path listed in another case.
- **Throttling:** the delete answers 503, the row stays, and the next report deletes it.
- Delivered: `FileSyncRepository.remove_file` and `record_activity`.
- Verified:
  - 7 new tests in `tests/integration/test_file_sync_ingest_uploads.py`. The 4 for deleting failed first. The 3 guards (an incomplete report, a skipped file, another case) passed before and after, because they check that nothing is deleted.
  - The file sync suites pass together (94 tests).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Upload links, empty files, skips and upload completion

- Changed: `POST …/file-sync/changes` answers 200 with `uploads` (`path`, `url`, `expires_at`). Each entry is compared, case-insensitively, with its `sync_file` row:
  - **Already synced with the same `sha256`:** nothing to do.
  - **Upload under way with the same content:** not reissued for 14 minutes (`UPLOAD_REISSUE_AFTER`); upload sessions last 15.
  - **Empty file:** written by the server (`write_empty_file`) and recorded as synced, with no upload.
  - **Anything else:** the plugin's `upload_target` under the Agent's folder, with the row marked under way (`upload_started_at`, `local_sha256`, `size`).
- Delivered: skips, recorded once per path and content (`sync_activity.detail` holds the `sha256`), with no upload:
  - over 100 MB: `skipped_too_large`;
  - a name the provider refuses, a path over 400 characters with the folder's path, or a second path in one report differing only in case: `skipped_name`.
- Delivered: `POST …/file-sync/uploads/complete {path}`.
  - It requires an upload under way at that path, reads the item by path from the provider, and requires a file of the reported size.
  - It then records `item_id`, `etag`, `ctag`, `remote_hash` and `synced_at`, and clears `upload_started_at`.
  - It never takes an item id from the pod. Otherwise it is 409.
- Delivered:
  - provider throttling answers 503 with the provider's `Retry-After` (60 s when none), and other provider failures 502;
  - every authenticated call sets the folder's `last_contact_at`.
- Changed:
  - `sync_root(connection)` is shared by the engine and the Ingest service;
  - `FileSyncRepository` gains `touch_folder`, `files`, `file_at`, `start_upload`, `record_synced` and `record_activity_once`.
- Fixed (tests):
  - Test Drive item ids are now unique per instance. Leftover connections from earlier tests in the same worker database had pointed at another instance's `td-1` root, so a global engine pass created their folders inside this test's root.
  - `test_file_sync_engine_pass.py` now starts from `database_is_clean`, because a pass reads every active connection in the database.
  - Both showed up as intermittent failures in combined runs.
- Verified:
  - `tests/integration/test_file_sync_ingest_uploads.py` (15 tests) failed first (15 of 15), then passed. They cover:
    - a new file's upload link and under-way row;
    - completion recorded from the provider and not asked for again;
    - a changed file;
    - not reissuing within 14 minutes, then reissuing;
    - an empty file;
    - a file over 100 MB, refused names and an over-long path, each recorded once;
    - case collisions;
    - three completion conflicts;
    - completion needing the key and an allowed path;
    - throttling;
    - `last_contact_at`.
  - The four authentication tests that expected 204 now expect 200.
  - The file sync suites passed four times in a row together (87 tests). Ingest, SharePoint token endpoint and sync provider connection suites pass (146 tests).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Pod file report route: authentication and refusals

- Delivered: `POST /ingest/v1/agents/{agent_id}/file-sync/changes` (`api/domains/file_sync/routes.py`, `FileSyncIngestService` in `service.py`), registered in the Ingest app.
  - **Body** (`FileSyncChangesCreate`): `complete` and up to 10,000 `entries`, each a `path` (1–1,024 characters), a `size` (≥ 0) and a lowercase hex `sha256`. A larger or malformed body is 422.
  - **Answer:** 204, without acting on the report yet.
- Refusals, in order:
  - **401:** a missing or wrong key, an Agent without a key, or an Agent that does not exist. All four answer alike.
  - **404:** a deleted Agent, even with its last valid key (deleting an Agent keeps its ingest key; only a start replaces it).
  - **409:** no active connection in the Agent's own Organization, or a provider without `file_sync`.
  - **404:** no folder yet, because the Sync Engine has not reached the Agent.
  - **409:** a folder that is not `active` (sync turned off), or not yet created at the provider.
  - **400:** a path not in NFC form, or `never` under the Agent's runtime's sync rules (malformed, outside the allowlist, credentials, `node_modules`, `_Not synced/`, …), naming the path.
- Delivered: `FileSyncRepository.agent_including_deleted` and `agent_sync_target`, which return the Organization's active connection and that Agent's folder on it.
- Changed: `api/ingest_app.py` imports the file sync and sync provider models and includes the router.
- Docs:
  - **[activity and ingest](../activity-and-ingest.md):** the route, its contract and refusals, and the source map.
  - **RBAC brief:** file sync pod traffic is Agent-authenticated machine traffic, with its tenant taken only from persisted rows. It is reachable from a router, so it is not background work.
- Verified:
  - `tests/integration/test_file_sync_ingest_auth.py` (30 tests). Before the route existed, 28 failed. The two expecting 404 passed only because every request was 404 then; they now pass against the route.
  - They cover:
    - Hermes and OpenClaw reports accepted;
    - each 401 case;
    - a deleted Agent;
    - not connected, a provider without `file_sync`, disconnected;
    - no folder yet, a folder not yet created, sync turned off;
    - nine refused paths and Hermes-specific rules;
    - five oversized or malformed bodies;
    - one Agent's key never opening another's;
    - an Agent judged only by its own Organization's connection.
  - The existing Ingest (`test_ingest.py`), SharePoint token endpoint, folder and engine pass suites pass (123 tests together).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Sync Engine deployment

- Delivered: `helm/agentbarn-api/templates/sync-engine-deployment.yaml`.
  - The Deployment runs `from api.sync_engine_main import main; main()` on the API image with the API Secret, and needs no LiteLLM, Redis or Kubernetes access.
  - It uses a non-overlapping rolling update (`maxSurge: 0`, `maxUnavailable: 1`) like the worker.
  - Its liveness probe fails when `/tmp/sync-engine-heartbeat` is older than `syncEngine.heartbeatMaxAgeSeconds` (120), after a 60 s initial delay.
  - Values: `syncEngine.enabled` (true), `replicaCount` 1, requests 192Mi / 50m, limits 384Mi / 500m.
  - API chart version 0.16.0 → 0.17.0.
- Delivered: `make dev-sync-engine`, written like the other host-run Python targets (`cd api && uv run python -c …`), and a `sync-engine` Compose service that `run.sh` builds and starts with the others.
- Docs:
  - **Sync provider README:** a new "Agent file sync" section (Sync Engine, Agent Folders, naming), the role and read-when updates, OneDrive's `file_sync` capability, and the source map.
  - **[runtime and deployment](../../architecture/runtime-and-deployment.md):** the Sync Engine Deployment.
  - **RBAC brief:** the Sync Engine among the background-work examples.
  - **Root `README.md`:** the dev target and `run.sh`'s services.
  - **`docs/INDEX.md`:** routes the engine.
- Verified:
  - **The chart:**
    - `helm template` of the API chart with placeholder required values renders the Deployment as above with the engine enabled, and nothing with `syncEngine.enabled=false`;
    - the whole chart renders, and `helm lint` passes;
    - CI has no Helm check.
  - **The liveness command,** run in `agentfarm-api:dev`: exit 1 without a heartbeat, 0 for a fresh one, 1 for one 180 s old.
  - **`docker compose config`** (with placeholder `WEB_APP_URL` and budget defaults) resolves the `sync-engine` service. `bash -n run.sh` passes.
  - **`make dev-sync-engine` on the host:**
    - it is written like `reconcile-restore-points` and the other host-run targets. On the verifying Windows machine those resolve `api` only with `PYTHONPATH=..`, a local quirk that applies to every such target, so the check below was run that way by hand;
    - with the two budget defaults the local `.env` lacks, it logged "Sync Engine started, one pass every 30s", logged each failed pass (no database on `localhost:5433`), wrote no heartbeat, and kept running;
    - on Windows, a signal sent through `make` and `uv` did not reach Python, so the leftover processes were stopped by hand. In the Deployment, Python is the container's command and receives SIGTERM itself; `test_sync_engine_main.py` covers stopping.
  - Every relative link in the edited docs resolves.

### 2026-10-22 — AF-384 — Sync Engine loop

- Delivered: `FileSyncEngine.run_pass(now)`. For every active connection with a root folder whose `sync_retry_at` is empty or due, oldest connection first:
  1. takes the connection's session-scoped advisory lock (`pg_try_advisory_lock`, the pattern Agents use), skipping a connection another engine holds;
  2. runs the folder pass;
  3. on `ProviderThrottled`, sets `sync_retry_at` to now plus the provider's `retry_after`, or 60 s when it gives none, and logs it;
  4. logs any other failure, including a provider no longer registered, and goes on with the other connections.

  Pending and disconnected connections are not synced.
- Delivered: `FileSyncRepository.due_connections`, `postpone` and `connection_lock`.
- Delivered: `api/sync_engine_main.py`.
  - `main()` builds the app injector and runs one pass every 30 s.
  - After each pass that completes, it touches `/tmp/sync-engine-heartbeat` for a liveness probe. A pass that raises is logged and does not touch the heartbeat, and the loop goes on.
  - SIGTERM and SIGINT end the loop at once, including during the wait.
- Verified:
  - `tests/integration/test_file_sync_engine_pass.py` (6 tests) and `tests/unit/test_sync_engine_main.py` (3 tests) failed first (`run_pass`, `connection_lock` and the module missing), then passed. They cover:
    - every active connection in one pass;
    - a postponed connection skipped until due;
    - throttling postponing only that connection by 120 s while the other still syncs;
    - a connection to an unregistered provider not stopping the others;
    - a held lock skipping the connection;
    - disconnected connections not synced;
    - the loop repeating, refreshing the heartbeat only on success, surviving a failing pass, and stopping during the wait.
  - The folder tests still pass (33 tests together). ruff, format and ty pass.

### 2026-10-22 — AF-384 — Folder reconciliation

- Delivered: `FileSyncEngine.reconcile_folders(connection)` in `api/domains/file_sync/engine.py`, with `FileSyncRepository` (`repository.py`). For an active connection whose provider declares `file_sync`, one pass:
  1. stops (`stopped`) the folder of every deleted Agent, without calling the provider; the folder stays there;
  2. reserves a folder row for every live Agent of the Organization without one, oldest Agent first. The database's unique name index decides who gets a name;
  3. creates the reserved folder under "Agent Barn" and records its item id, link and server-relative path. A failed create leaves the row reserved, and the next pass creates it;
  4. renames the folder when the Agent's name changed.
- **Folder names:**
  - `: " * < > ? | \ /` and control characters become `-`;
  - spaces are trimmed, and trailing dots removed;
  - an empty name, or one the provider refuses (a reserved name such as `CON`, or the `_vti_` prefix), becomes `Agent`;
  - names are at most 255 characters, cut before ` (n)` is added.
- **Duplicates:**
  - Duplicates, compared case-insensitively, get the lowest free ` (2)`, ` (3)`… Names of stopped and disabled folders stay taken, so a new Agent named like a deleted one gets a number.
  - A name already used at the provider (`RemoteNameTaken`) moves on to the next number.
  - A numbered name drops its number once the plain name is free, so two Agents swapping names settle within two passes without ever sharing a name.
- **Skipped:** disabled folders, a provider without `file_sync`, and a connection without a root folder. A pass with nothing to do makes no provider call. Throttling and other provider failures propagate to the caller, the engine loop that arrives in the next slice.
- **Tenant scoping:** queries are by the connection's own Organization and connection id, read from persisted rows. Only the engine calls them, never a router.
- Changed (plan):
  - **People's own folder changes move to remote change processing.** A person renaming or deleting an Agent's folder, or the "Agent Barn" root, is detected there from the change feed, instead of by asking the provider about every folder on every pass (one call per Agent every 30 s).
  - **README section:** the "Agent file sync" section lands with the engine process, because nothing runs this pass yet.
- Changed: `tests/steps/file_sync_provider.py` gains `TestDriveModule` (Test Drive and Other Drive beside the shipped plugins), `fake_drive` and `there_is_a_sync_connection`.
- Verified:
  - `tests/integration/test_file_sync_folders.py` (24 tests) failed first (engine missing), then passed. It covers:
    - connecting with existing Agents, a later Agent, and a pass with nothing to do;
    - duplicates, including case-only ones;
    - eight naming cases and long names;
    - rename, a swap, and a number dropped;
    - delete and name reuse;
    - a disabled folder;
    - a name taken at the provider;
    - a create retried after throttling;
    - a provider without `file_sync`;
    - another Organization's Agents.
  - Sync provider connection, repository, schema and plugin suites pass (213 tests together).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — Test-only `file_sync` provider

- Delivered: `TestDrivePlugin` (key `testdrive`) in `api/tests/steps/file_sync_provider.py`. It declares only `file_sync` and keeps an in-memory folder tree with a change log.
  - **Plugin calls** behave like OneDrive's:
    - paths are relative to the root folder;
    - a content edit changes both versions, and a rename or move only `version`;
    - deleted items have no name or path;
    - names are taken case-insensitively;
    - deleting an item already gone is not an error;
    - changes start from now or from the beginning, in pages of `page_size` with `more`;
    - an upload replaces the file only when the pod completes it;
    - empty files are written without an upload.
  - **Test helpers:**
    - acting as a person at the provider: `user_adds`, `user_edits`, `user_deletes`, `user_renames`, `user_moves`, `user_moves_outside`;
    - acting as the pod: `complete_upload` and `content_at`;
    - failures: `throttle_next(retry_after)` throttles the next call once, and `expire_cursors` makes stored cursors need a resync.
  - `OtherDrivePlugin` still declares no capability, so tests can show that a connection without `file_sync` is skipped.
- Verified:
  - `tests/unit/test_test_drive_file_sync.py` (12 tests) failed first (module missing), then passed. It holds the fake to the contract the OneDrive tests show: registry acceptance, paths, name conflicts, version semantics, deletion, change pages and cursors, resync, throttling once, uploads landing on completion, downloads, empty files, and a move out of the root losing its path.
  - `test_sync_provider_plugins.py` still passes.
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — OneDrive implements `file_sync`

- Delivered: `OneDriveSyncProviderPlugin` declares `file_sync` and implements its nine methods on `MicrosoftGraphFiles`.
  - **Who it acts as:** the platform app in the connection's tenant, with a token from `MicrosoftAppTokens`.
  - **Paths:** Microsoft's `parentReference.path` (`/drives/…/root:/Agent Barn/Sales Bot/workspace`) becomes a path relative to the root folder (`Sales Bot/workspace/notes.md`), matching the root case-insensitively. The root itself, anything outside it, a sibling such as "Agent Barnyard", and deleted items have no path.
  - **Change feed:** with no cursor it starts from now (`token=latest`), or from the beginning when asked. A page's `nextLink` or `deltaLink` becomes the cursor to store, with `more` set when a `nextLink` is waiting. A page with neither is `ProviderUnavailable`.
  - **Failures:**

    | Graph | Neutral failure |
    |---|---|
    | 404 | `RemoteItemMissing` |
    | 409 | `RemoteNameTaken` |
    | 400, 412 | `RemoteChangeRejected` |
    | 410 | `RemoteResyncRequired` |
    | 401, 403, or a refused app token | `LocationAccessRefused` ("Agent Barn no longer has access to the SharePoint site. Connect OneDrive again.") |
    | 429 | `ProviderThrottled`, with Microsoft's `Retry-After` |
    | anything else, including an unreachable Microsoft | `ProviderUnavailable` |

    A root without a site is `LocationNotFound` before anything is called.
- Changed:
  - `shipped_plugins` takes `MicrosoftGraphFiles` and `MicrosoftAppTokens`, wired in `AppModule` and `tests/steps/sync_provider.py`.
  - `MicrosoftAppTokens` marks its test clock `NoInject`, because the injector otherwise refuses to build it.
  - Connect-time provisioning still mints its app token directly, unchanged.
  - `GET …/sync-providers` now lists `file_sync` among OneDrive's capabilities.
- Not changed: the Playwright data support (`sync-provider-data-support.po.ts`) still mocks OneDrive's capabilities without `file_sync`. The UI only looks for `location_picker`.
- Verified:
  - 28 new OneDrive tests in `tests/unit/test_sync_provider_plugins.py` failed first (`shipped_plugins` refused the new arguments), then passed. They cover:
    - the app token per tenant, fetched once and reused;
    - item mapping and relative paths, including the edge cases;
    - deleted items;
    - the change feed start, cursor and `more`;
    - every write's request;
    - each failure mapping, `Retry-After`, a refused or unreachable token, and a root without a site.
  - The first integration run had 123 failures: the injector could not build `MicrosoftAppTokens`. After `NoInject`, the only failure left was the provider list's expected capabilities, which were updated.
  - Plugin, connection, repository and SharePoint (selected sites, sign-in, token endpoint) suites pass (276 tests together).
  - ruff, format and ty pass.

### 2026-10-22 — AF-384 — `file_sync` capability on the plugin seam

- Delivered: `SyncProviderCapability.FILE_SYNC`, and in `plugins/base.py`:
  - **Neutral types:**
    - `SyncRoot` (account, location, "Agent Barn" folder id and name);
    - `RemoteItem`, with its path relative to "Agent Barn", `version` (any change), `content_version` (content only), size, content hash, folder and deleted flags, and modified time and by-app flag;
    - `RemoteChanges`, a page with the cursor to store and `more`;
    - `UploadTarget`, a URL and its expiry.
  - **Nine methods**, which raise `NotImplementedError` unless a plugin declares the capability: `create_folder`, `get_item`, `get_item_by_path`, `move_item`, `delete_item`, `changes`, `upload_target`, `download_url`, `write_empty_file`.
  - **Typed failures:** `RemoteItemMissing`, `RemoteNameTaken`, `RemoteChangeRejected` and `RemoteResyncRequired`. `ProviderThrottled` gains an optional `retry_after`.
- Delivered: the registry refuses a plugin that declares `file_sync` without all nine methods.
- Changed:
  - README "Adding a provider" step 3 names the `file_sync` methods and their contract.
  - The capability appears in `GET …/sync-providers` `capabilities` only once a plugin declares it. The UI accepts any capability string (`schemas.ts`), and `api/developer_docs/operations-v1.json` lists no capability values.
- Changed (plan): disconnect deletes the Agent folders with the app's own access, before the grant is revoked, instead of with the administrator's fresh sign-in. No extra method is needed.
- Verified:
  - 15 new tests in `tests/unit/test_sync_provider_plugins.py` failed first (types missing), then passed. They cover:
    - the exact method list;
    - a full implementation accepted;
    - each of the nine methods missing refused;
    - a plugin without the capability refusing file calls;
    - `retry_after`;
    - the failure types.
  - `test_sync_provider_connection.py` and `test_sync_provider_repository.py` pass (173 tests together).
  - ruff, format and ty pass.

### 2026-10-21 — AF-384 — Graph file operations and app-token cache

- Delivered: `MicrosoftGraphFiles` in `api/domains/agents/microsoft_graph_files.py`. Every call is made as the app in one site's default library (`/sites/{site_id}/drive`):
  - **reading items:** `get_item` and `get_item_by_path`, with each path segment percent-encoded;
  - **creating, moving and deleting:**
    - `create_folder` (conflict behaviour `fail`);
    - `move_item` (rename, move or both);
    - `delete_item` (recycle bin; an item already gone is not an error);
  - **the change feed:** `delta_start_url` (from now with `token=latest`, or from the beginning) and `delta_page`, which follows absolute `nextLink`/`deltaLink` URLs and keeps deleted items, which have only an id and a parent id;
  - **links for the pod:** `create_upload_session` (conflict behaviour `replace`, returns the URL and its expiry) and `download_url`;
  - **empty files:** `put_empty_file` writes 0-byte files, because upload sessions refuse them.

  `DriveItem` carries:
  - `eTag`, `cTag`, `quickXorHash` and `size` (0 for folders, whose delta size can be negative);
  - the parent id and path, and `deleted`;
  - `modified_by_app`, true when `lastModifiedBy` names an application.
- Delivered: typed failures.
  - `GraphItemNotFound` (404) and `GraphAccessRefused` (401/403).
  - `GraphRequestRejected` (400), `GraphNameConflict` (409), `GraphResyncRequired` (410), `GraphPreconditionFailed` (412), and `GraphThrottled` (429) with the full `Retry-After` in seconds. These are all `GraphUnavailable`, so a caller that undoes on any failure still does.
- Delivered: `MicrosoftAppTokens` in `microsoft_identity.py`.
  - App-only tokens per tenant and app, held in process memory.
  - Reused until 5 minutes before expiry.
  - A failed fetch is not remembered.
- Changed: `retry_after_seconds` takes `max_seconds`. The default stays 30 s for every existing caller, and `None` lifts the cap for callers that schedule the retry instead of sleeping.
- Not changed: `microsoft_graph_sites._call`, which the SharePoint integration and the connect flow use. The file client has its own request handling instead of a refactor of the shared one.
- Verified:
  - `tests/unit/test_microsoft_graph_files.py` and `test_microsoft_app_tokens.py` (33 tests) failed first (module and class missing), then passed. Their payloads are copied from the PR 0 run against the test site.
  - Identity, Graph sites, plugin, Slack, Discord, Teams, Telegram, Communications error-detail and Communication Connection suites pass (253 tests together).
  - ruff, format and ty pass.
- Follow-up, for the end-to-end run (PR 0 used `/drives/{id}`, not these forms):
  - `/sites/{site_id}/drive/items/…` addressing for delta, moves and upload sessions;
  - whether an upload session at a nested path creates the missing parent folders.

### 2026-10-21 — AF-384 — File sync tables

- Delivered: models in `api/domains/file_sync/models.py` and migration `af95cf4c3a1e` (revises `a4e9c2d7b615`), registered in `api/migrations/env.py`.
  - **`sync_agent_folder`:** one Agent's folder on a connection.
    - Columns: `folder_item_id`, `folder_web_url`, `folder_path`, `status` (`active`/`stopped`/`disabled`) and `last_contact_at`.
    - One folder per Agent per connection.
    - Folder names are unique per connection, case-insensitively.
  - **`sync_file`:** one synced path.
    - What both sides last agreed on: `item_id`, `etag`, `ctag`, `remote_hash`, `local_sha256`, `size` and `synced_at`. The provider fields are empty while the first upload is under way (`upload_started_at`).
    - Work only the pod can do: `pending` (`download` or `reupload`), claimed until `lease_until`, with `attempts` and `retry_at`. One row per path means at most one open job per file.
    - Paths are unique per folder, case-insensitively, matching the provider (PR 0: `notes.md` next to `Notes.md` is 409).
    - Each provider item is recorded once per folder, so a deleted item, which carries only its id, can be matched.
  - **`sync_activity`:** what a person should be able to see. It is indexed by Agent and time, and keeps its rows (`folder_id` set to null) when the folder row goes.
  - **Cascades:** folders and files go with their connection, Agent or Organization. Activity goes with its Agent or Organization.
  - **`sync_provider_connection`:** gains `sync_cursor` and `sync_retry_at`.
- Changed:
  - Repository queries arrive with the slice that uses them, not here, so no query is written before its caller exists.
  - `api/ingest_app.py` imports the new models when the Ingest routes land.
- Verified:
  - `api/tests/integration/test_file_sync_schema.py` (12 tests) covers:
    - each uniqueness rule, and several first uploads under way without a provider item;
    - defaults and pending work stored on the file;
    - the connection columns;
    - files removed and activity kept when a folder goes;
    - the Organization delete cascade, and a soft-deleted Agent keeping its folder.

    The first five-table version failed first (models missing). The three-table rewrite was written together with its models, so it did not fail first.
  - A one-off autogenerate comparison of the models against a database migrated to head found no difference in the four affected tables. The raw diff text was also searched for every table and new column name, with no match.
  - One Alembic head (`af95cf4c3a1e`).
  - `test_sync_provider_repository.py`, `test_sync_provider_connection.py` and `test_sync_provider_plugins.py` still pass.
  - ruff, format and ty pass.

### 2026-10-21 — AF-384 — Sync rules

- Delivered: `api/domains/file_sync/rules.py`.
  - **`classify(runtime, path)`** sorts a path relative to the Agent's volume into a Sync Category.
    - Hermes (root `/opt/data`):
      - memory: `memories/USER.md`, `memories/MEMORY.md`;
      - config: `SOUL.md` and `workspace/{IDENTITY,AGENTS,TOOLS,BOOT,HEARTBEAT}.md`;
      - skills: `workspace/skills`;
      - work: the rest of `workspace/`.
    - OpenClaw (root `/home/node/.openclaw`):
      - memory: `workspace/USER.md`, `workspace/MEMORY.md`;
      - config: `workspace/{SOUL,IDENTITY,AGENTS,TOOLS,BOOT,BOOTSTRAP,HEARTBEAT}.md`;
      - skills: `workspace/skills`;
      - work: the rest of `workspace/`.
    - Config and skills entries match the entry itself and anything under it, as the Restore Point exclusions do.
    - Never: everything else, `.git`, `node_modules` and `__pycache__` anywhere, `_Not synced/`, and malformed paths (empty, absolute, `.` or `..` or empty segments, backslashes, control characters).
  - **`name_problem(path)`** reports a name the provider refuses:
    - forbidden characters `: " * < > ? | \`;
    - a leading space;
    - a trailing dot or space;
    - the Windows reserved device names, with or without an extension: `CON` and `aux` were observed, and `PRN`, `NUL`, `COM0-9` and `LPT0-9` are refused with them;
    - the `_vti_` prefix.
  - **`path_too_long`** applies the 400-character server-relative path limit.
  - **`MAX_FILE_BYTES`** is 100 MB.
  - **`rules_manifest(runtime)`** is the JSON form of the rules for the in-pod helper.
- Changed: `docs/INDEX.md` routes `api/domains/file_sync/`.
- Verified:
  - `api/tests/unit/test_file_sync_rules.py` (118 tests) failed first (module missing), then passed.
  - **Drift guards.** Expectations are derived from the code, not restated:
    - the credentials and machinery entries of `HERMES_EXCLUDED`/`OPENCLAW_EXCLUDED` (and anything under them) are `never`;
    - nothing either tuple excludes is `work` or `memory`;
    - Hermes config comes from `start.sh`'s copy loop plus `SOUL.md`;
    - OpenClaw config comes from every `.md` key `build_config_map` writes except `USER.md`.
  - The first green run caught `workspace/skills` itself, and paths under a config entry, classified as `work`; prefix matching fixed both.
  - ruff, format and ty pass for the new files.
  - `test_restore_point_job.py` has the same 7 symlink failures with and without this change; they are a local Windows limit on creating symlinks.

### 2026-10-21 — AF-384 — ADR and glossary

- Delivered: [ADR 2026-10-21 — Agent files sync two ways through the Sync Provider](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md). It records:
  - the ticket's four constraints;
  - the maintainer's choices: version history instead of conflict copies, folders from the engine pass, and the generic capability;
  - the accepted Organization Member visibility limit.
- Changed:
  - `CONTEXT.md` adds Agent Folder, File Sync and Sync Category.
  - The Sync Provider Connection entry now says no Agent is given the provider's credentials, replacing "no Agent is given access to it".
  - This log gains the AF-384 current state and acceptance criteria amendments.
  - `docs/INDEX.md` routes the new ADR from the sync providers row and names AF-384 on this log's row.
- Not changed yet: the README, RBAC brief, Agents, activity-and-ingest, runtime-and-deployment, operations and INDEX docs still describe current behaviour. The AF-384 current state above lists the slice that updates each one.
- Verified: every relative link added in this slice resolves.

### 2026-10-21 — AF-384 — Microsoft and runtime image verification (no code)

- Verified against the test site `AgentBarnTest` (tenant `aailabs`) with the platform app's app-only token. Each line is an observed response, not a documented claim.
  - **Change feed (T-1):**
    - `delta` works on a folder (`/items/{Agent Barn id}/delta` → 200) as well as on the drive root with `token=latest`. Items carry `parentReference.path`, `eTag`, `cTag`, `size` and `file.hashes.quickXorHash`.
    - `cTag` changes only with content: a rename and a move kept `cTag` `…},3` while `eTag` went to `…},5`.
    - A deleted item has only `id`, `parentReference.id` and `deleted.state`, with no name and no path.
    - In delta, `lastModifiedBy.application` has `displayName` only, with no `id`. The upload response does carry the app `id`.
    - Changes also report every ancestor folder and the drive root. Folder `size` in delta can be negative.
  - **Writes as the app:** rename and move return 200, delete returns 204, and the deleted file appears in the site recycle bin.
  - **Version history is on:** after the app uploaded over a person's edit, `versions` listed 1.0 (app), 2.0 (the person) and 3.0 (app).
  - **Pre-authenticated links:**
    - `@microsoft.graph.downloadUrl` returns 200 with no `Authorization` header.
    - From a k3d pod on `agentfarm-hermes-base:dev` with no token, a 1 MiB file uploaded in two chunks to an `uploadSession` URL (202, then 201 with `id`, `eTag`, `cTag` and `quickXorHash`), and a `downloadUrl` returned 200.
    - Upload sessions expire 15 minutes after creation.
    - A 0-byte `PUT` to an upload session without `Content-Range` is refused with 400.
  - **Autosave (T-3):**
    - Word for the web saved a new document as `Document.docx` and renamed it to `autosave.docx` 12 s later.
    - While typing, saves came 2–45 s apart, and no save came after typing stopped.
    - A browser text edit is one save.
  - **Names and paths (T-4):**
    - Refused for files and folders: `: " * < > ? |`, a leading space, the reserved names `CON` and `aux` (also `CON.txt`), and the `_vti_` prefix (files 403).
    - Also refused for folders: `\`, a trailing `.` and a trailing space. Files were tested with a `.txt` suffix, so a trailing `.` or space on a file name is unverified.
    - Accepted: `#`, `%`, `.lock`, `~$lock`, `desktop.ini`, `forms`, and 255- and 256-character names.
    - The server-relative path is limited to 400 characters (Microsoft's message: "must be 400 characters or less").
    - Names are case-insensitive: `notes.md` next to `Notes.md` gives 409 `nameAlreadyExists`.
  - **Throttling:** no 429 was seen.
- Verified in the runtime images with `docker run`:
  - Hermes (`agentfarm-hermes-base:dev`): `python3` is `/opt/hermes/.venv/bin/python3`, 3.13.5.
  - OpenClaw (`agentfarm-openclaw-base:dev`): `/usr/local/bin/python3`, 3.12.15.
  - OpenClaw 2026.8.2's own code reads `MEMORY.md` and `USER.md` from the workspace root and daily notes from `workspace/memory/*.md`.
- Changed (plan, before any code):
  - **Change detection:**
    - content edits are detected by `cTag`, renames and moves by `eTag`;
    - deleted items are matched by item id;
    - our own uploads are recognised by recorded tags and pending uploads, not by an app id.
  - **Pod helper uploads:** the helper asks for an upload URL just before each upload and asks again when one expires.
  - **Empty files:** the server creates 0-byte files itself.
  - **Settle delay:** 30 s after an item's last change.
  - **Name rules:** they follow the refused list above, treat a trailing `.` or space as refused for every name, and apply the 400-character path limit.
- Follow-up: in PR 15, check the download URL lifetime, a trailing `.` or space on file names, incremental folder `delta` over time, how deleting a folder with children appears in the feed, and 429 if it appears.

### 2026-10-16 — AF-383 — OneDrive logo in the Sync list

- Delivered: `ui/public/brand/onedrive.svg` (a drawn cloud mark in OneDrive's blues), `OneDriveIcon` and `syncProviderIcon` in `ui/src/components/brand-icons.tsx`. The Sync row shows the mark for `onedrive` and keeps the letter tile for a provider without one.
- Changed: `README.md` (row description, "Adding a provider" step 7).
- Verified: a new test in `ui/tests/e2e/sync-provider.spec.ts` (the OneDrive logo is an image named "OneDrive" that loads; a provider without a mark has no image) failed first. The spec's 21 tests pass, and `tsc` and eslint pass.

### 2026-10-16 — AF-383 — Docs move to `docs/features/sync-provider/`, ADR

- Changed:
  - `docs/features/onedrive-sync/` moved to `docs/features/sync-provider/`. The README is now generic (provider list and routes, connection lifecycle, failure mapping, one connection at a time, Sync settings, **Adding a provider**), with an **OneDrive provider** section for everything Microsoft.
  - This log's current state is rewritten for the seam.
  - `CONTEXT.md` replaces "OneDrive Sync Connection" with **Sync Provider** and **Sync Provider Connection**.
  - `docs/INDEX.md` routes to the new folder and the ADR, and `docs/features/integrations.md` links the OneDrive section.
- Delivered: [ADR 2026-10-16 — sync provider plugin seam](../../adr/2026-10-16-sync-provider-plugin-seam.md), recording the maintainer's reason (Dropbox and Google Drive will be added and should be simple to add) and the one-connection-at-a-time rule.
- Verified: every relative link in the moved README, this log, the ADR, `docs/INDEX.md`, `CONTEXT.md` and `integrations.md` resolves to an existing file. No doc names the removed `onedrive_sync` domain or `onedrive-sync` paths outside the history below.
- Follow-up: the manual run against the test tenant.

### 2026-10-16 — AF-383 — Sync settings: the provider list (Option B)

- Delivered: Settings → **Sync** (`?tab=sync`), replacing Settings → OneDrive. It's built from `ui/src/features/sync-provider/` and shows one row per offered provider from `GET …/sync-providers`:
  - each row has a letter tile, the provider's name, and a subtitle (tagline, "Connecting…" or "● Connected to {location}");
  - **Connect**, **Open** and **Disconnect** appear by role;
  - the row expands with the inline location picker and **Start over**, the folder hint, the connect hint, the approval link, or the server's `blocked_reason`.

  The UI has no provider-specific branches.
- Changed: the provider entry carries `connect_hint` and `location_noun` from the plugin, so provider wording stays in the plugin; the registry requires `location_noun` for a location picker. The disconnect dialog says the folder stays "where it is" rather than "in SharePoint". The popup message type is `sync-provider-oauth`. `ui/src/features/onedrive-sync/` and its Playwright spec, page object and data support are removed. `README.md` (Organization settings, list fields, source map) and `docs/INDEX.md` are updated.
- Verified:
  - `ui/tests/e2e/sync-provider.spec.ts` (20 tests, all failing before the UI existed). It covers the list, empty and failing states, both roles, the connect hint and approval link, a second provider blocked with the server's reason, no picker without the capability, a provider without a picker connecting at sign-in, the full OneDrive connect flow with exactly one search, the callback error, a refused site, disconnect, a refused disconnect, and Start over.
  - The Shared Credentials, Spend limits and Agent defaults specs pass. `tsc` and eslint pass.
  - API: plugin tests (`connect_hint`, `location_noun` and the registry check), `test_sync_provider_connection.py` and the contract test pass.
- Follow-up: docs move to `docs/features/sync-provider/`, the ADR, and the manual run with the new redirect URI.

### 2026-10-16 — AF-383 — Generic sync provider service and routes; `onedrive_sync` removed

- Delivered: `SyncProviderService` and provider-keyed routes in `api/domains/sync_provider/`, replacing `api/domains/onedrive_sync/`:
  - `GET /organizations/{organization_id}/sync-providers` lists every offered provider with its descriptor, `approval_url`, `connection`, `can_connect` and `blocked_reason`;
  - `…/sync-providers/{provider_key}/connection/` `authorize-url`, `sign-in`, `locations`, `location`, `disconnect`, and `DELETE` to abandon;
  - the callback is `GET /api/v1/integrations/sync-provider/{provider_key}/callback`.

  Plugin failures map to the same status codes as before. The SharePoint location guard is bound in the service, from the plugin's `SyncLocationGuard`. A provider without a location picker is provisioned at sign-in.
- Delivered: one connection at a time, in `SyncProviderService._blocking_connection` and the partial unique index. Another provider's live connection blocks with 409 "Disconnect OneDrive first.", or "Finish connecting OneDrive, or start over, first." while it's pending. Expired sign-ins don't block and are cleared at the next sign-in (`SyncProviderRepository.delete_expired_pending`).
- Changed:
  - an unconfigured provider is left out of the list, and its routes are 404 instead of 503;
  - the popup message type is `sync-provider-oauth`;
  - migration `734b0f2b3793` (renamed `…_add_sync_provider_connection.py`) creates only `sync_provider_connection`;
  - `SharePointService` reads the folder site through `SyncProviderLookupService`;
  - the redirect URI in `.env.spec`, `.env.deploy.spec` and the API chart values is `<WEB_APP_URL>/api/v1/integrations/sync-provider/onedrive/callback`;
  - `README.md` (routes, one connection at a time, changing to several providers, source map), `docs/INDEX.md`, and `api/developer_docs/operations-v1.json` (8 operations removed, 8 added, nothing else changed).
- Verified:
  - `api/tests/integration/test_sync_provider_connection.py` (82 tests): every ported OneDrive case on the new routes, the provider list, unknown and unoffered providers, another provider's state, a provider without a picker, and the one-connection-at-a-time group, using a test-only second provider (`api/tests/steps/sync_provider.py`);
  - `test_sync_provider_repository.py` (20); the plugin, config and contract tests; `test_sharepoint_selected_sites.py`, `test_sharepoint_sign_in.py` and `test_sharepoint_token_endpoint.py`;
  - ruff, format and ty (only the existing Unix-only errors remain); one Alembic head;
  - a one-off autogenerate comparison found no difference for `sync_provider_connection`.
- In transition: the Organization settings UI still calls the removed `/onedrive-sync` routes until the next slice. The Microsoft app needs the new redirect URI registered before a manual run.
- Follow-up: the Sync settings UI (Option B connection list).

### 2026-10-16 — AF-383 — Sync provider connection table, repository and lookup

- Delivered: `SyncProviderConnection` (`sync_provider_connection`) in `api/domains/sync_provider/models.py`:
  - keyed by `provider_key`, with `schema_version` (checked positive), `account_id`, the location and folder, JSON `provider_data` and `credentials_encrypted` for the pending token;
  - the partial unique index `uq_sync_provider_connection_open` keeps one open connection per Organization across providers.
- Delivered: `SyncProviderRepository` (every method takes the provider key; `list_open` lists an Organization's open connections) and `SyncProviderLookupService.folder_location_id(organization_id, provider_key)`.
- Changed: unreleased migration `734b0f2b3793` now also creates `sync_provider_connection`. `onedrive_sync_connection` stays until the old domain is removed in the next slice. `api/migrations/env.py` imports the new models.
- Verified:
  - `api/tests/integration/test_sync_provider_repository.py` (18 tests, run through the migrations), including one open connection across providers;
  - `test_onedrive_sync_repository.py` still passes;
  - a one-off autogenerate comparison found no difference between the model and the migrated schema. Server defaults were left out of that comparison, because Alembic can't compare JSON defaults on Postgres.
  - One Alembic head.
- Follow-up: the generic service and provider-keyed routes; remove `api/domains/onedrive_sync/` and its table.

### 2026-10-16 — AF-383 — Sync provider seam and OneDrive plugin

- Delivered: `api/domains/sync_provider/plugins/`, modelled on the Communications Platform Plugins:
  - `SyncProviderPlugin` (`base.py`) with capabilities `location_picker` and `admin_approval`, the location guard `SyncLocationGuard.SHAREPOINT_AGENT_SITES`, and typed failures;
  - `SyncProviderPluginRegistry` (`registry.py`), which checks keys, schema versions, the location guard, and that each declared capability's methods are implemented;
  - `OneDriveSyncProviderPlugin` (`onedrive.py`), holding the Microsoft sign-in, site search, grant, folder, rollback and revoke logic from `OneDriveSyncService`;
  - `shipped_plugins` (`providers.py`), registered in `AppModule`.

  Nothing calls the seam yet; `onedrive_sync` behaves as before.
- Changed: the test fake `FakeMicrosoftGraphSites` can fail a site search (`search_failure`).
- Verified: `api/tests/unit/test_sync_provider_plugins.py` (53 tests) covers the contract sweep over shipped plugins, every registry rejection, and the OneDrive plugin's requests and failure mapping. `test_onedrive_sync_connection.py` and `test_sharepoint_selected_sites.py` pass unchanged.
- Follow-up: the generic `sync_provider_connection` table, repository and lookup.

### 2026-10-14 — AF-383 — Merge staging: imports and migration heads

- Changed: merge revision `0219de43e2c9` joins `734b0f2b3793` (OneDrive sync connection) and staging's `b3d8e1f4a6c2` (trial onboarding) into one Alembic head. `api/api_app.py` and `api/migrations/env.py` import `onboarding` before `onedrive_sync`, as ruff requires.
- Verified: ruff, format, one Alembic head, the OneDrive repository and connection suites (migrating through the merged chain), the public API contract test, and the OneDrive Playwright spec.

### 2026-10-14 — AF-383 — No site search after the picker closes

- Fixed: choosing a site or starting over refetched the active site search against a connection that was no longer pending, which the API answered with 409 (seen in the local API log during the manual run). `useChooseOneDriveSite` and `useAbandonOneDrive` now remove the cached searches instead of invalidating them.
- Verified: the connect-flow test in `ui/tests/e2e/onedrive-sync.spec.ts` asserts that exactly one search was sent; it failed before the fix. Lint and type check pass.

### 2026-10-14 — AF-383 — Connect starts at sign-in; one-time approval link

- Delivered: `authorize-url?purpose=connect` returns Microsoft's sign-in URL instead of admin consent. Status carries `approval_url` (`.default` admin consent at `organizations`, no state). The callback's `admin_consent=True` shows an "approved" page instead of redirecting. The settings section gives Owners and Admins the approval link. The PKCE challenge is no longer carried in the state.
- Changed: `README.md` (connect flow, Organization settings, Known limits).
- Verified: updated and new tests in `api/tests/integration/test_onedrive_sync_connection.py` (sign-in URL for connect, `approval_url` present or absent, the approved page without the tenant) and `ui/tests/e2e/onedrive-sync.spec.ts` (approval link for Owners, not Members); the contract test, lint and type checks pass.
- Follow-up: the manual run against the test tenant.

### 2026-10-14 — AF-383 — Disconnect and Start over in the UI

- Delivered: `useDisconnectOneDrive` and `useAbandonOneDrive`, the Disconnect control behind `ConfirmationDialog`, and Start over under the site picker.
- Changed: `README.md` (Organization settings, Known limits).
- Verified: 4 new tests in `ui/tests/e2e/onedrive-sync.spec.ts` (disconnect with recorded requests, a refused disconnect keeping the connection, a Member without the control, Start over); the Shared Credentials, Spend limits and Agent Memory specs still pass; lint and type check pass.
- Follow-up: the manual run against the test tenant.

### 2026-10-14 — AF-383 — Connect flow and site picker in the UI

- Delivered: `useConnectOneDrive`, `useOneDriveSyncSites` and `useChooseOneDriveSite` (`hooks/use-onedrive-sync-actions.ts`, reusing `openOAuthPopup` / `waitForOAuthPopupMessage`), `components/onedrive-site-picker.tsx`, and the Connect control in the panel.
- Changed: `README.md` (Organization settings). The PR 12 test for a pending connection now uses a Member, because Owners and Admins see the picker there instead of the note.
- Verified: 7 new tests in `ui/tests/e2e/onedrive-sync.spec.ts` (full connect flow with recorded requests, resuming at the picker, search needs a term, the Global Administrator error, a refused site, Member and unavailable have no controls); the Shared Credentials and Spend limits specs still pass; lint and type check pass.
- Follow-up: disconnect and Start over in the UI.

### 2026-10-14 — AF-383 — Organization settings section

- Delivered: `ui/src/features/onedrive-sync/` (schema, query key, status query hook, panel) and the `onedrive-sync` section in Organization settings, visible to every Member.
- Changed: `README.md` (Organization settings), `docs/INDEX.md`.
- Verified: `ui/tests/e2e/onedrive-sync.spec.ts` (6 tests) with `OneDriveSyncDataSupport` and `SettingsOneDriveSyncPage`; the Shared Credentials, Spend limits and Agent Memory specs still pass; lint and type check pass.
- Follow-up: the Connect button moved to the connect-flow slice, where it does something. The query is keyed by Organization id instead of being added to the org-switch deny-list (`docs/guidelines/webapp.md` allows either).

### 2026-10-14 — AF-383 — SharePoint guard for the folder site

- Delivered: `SharePointService._refuse_onedrive_folder_site`, called in `_complete_site_grant` after new site ids are resolved and before any grant, via `OneDriveSyncLookupService`.
- Changed: `docs/features/integrations.md` (SharePoint selected sites) and `README.md` describe both directions of the guard and the delegated-mode gap.
- Verified: 4 new tests in `api/tests/integration/test_sharepoint_selected_sites.py` (refused alongside another site with nothing granted or saved, case-insensitive match, other sites still granted, another Organization's folder site not blocking). All existing tests in `test_sharepoint_selected_sites.py`, `test_sharepoint_sign_in.py`, `test_sharepoint_token_endpoint.py` and `test_onedrive_sync_connection.py` pass.
- Follow-up: the Organization settings UI.

### 2026-10-14 — AF-383 — Disconnect

- Delivered: `OneDriveSyncService.disconnect` and `POST …/connection/disconnect`. The state check and the code redemption are shared with sign-in (`_verified_state`, `_redeem`).
- Changed: `README.md` disconnect flow; `api/developer_docs/operations-v1.json` with the new operation.
- Verified: 10 new tests in `api/tests/integration/test_onedrive_sync_connection.py` cover the revoke, reconnecting afterwards, another tenant, tenant case, a refused or failed revoke keeping the connection, missing scope, wrong state purpose or user, not connected, and a Member.
- Follow-up: the SharePoint integration guard.

### 2026-10-14 — AF-383 — Refuse a site an Agent already holds

- Delivered: `AgentRepository.list_secrets_for_organization` (soft-deleted Agents included) and `SharePointService.organization_site_ids`, used by `OneDriveSyncService.choose_site` before any grant. `SharePointService._stored_content` now shares its decryption with the new method.
- Verified: 4 new tests in `api/tests/integration/test_onedrive_sync_connection.py` (held site, held by a deleted Agent, held site elsewhere, another Organization's Agent). `test_sharepoint_selected_sites.py`, `test_sharepoint_sign_in.py` and `test_sharepoint_token_endpoint.py` pass unchanged.
- Follow-up: disconnect.

### 2026-10-14 — AF-383 — Site picker, grant and folder

- Delivered: `OneDriveSyncService.sites` and `choose_site` with `GET …/connection/sites` and `POST …/connection/site`.
- Changed: `README.md` connect flow; `api/developer_docs/operations-v1.json` with the two new operations; the test fake `FakeMicrosoftGraphSites` in `api/tests/steps/sharepoint.py` gains `search_sites`, `get_site` and `ensure_folder`, and records the grant's display name.
- Verified: 16 new tests in `api/tests/integration/test_onedrive_sync_connection.py` cover search, permissions, an expired or missing sign-in, the grant shape, the app-only folder call in the connection's tenant, activation, and revoking the grant when the app token or folder fails. `test_sharepoint_selected_sites.py` and `test_sharepoint_sign_in.py` pass unchanged.
- Follow-up: refuse connecting to a site already granted to an Agent.

### 2026-10-14 — AF-383 — Sign-in to a pending connection, and abandon

- Delivered: `OneDriveSyncService.complete_sign_in` and `abandon_pending` with `POST …/connection/sign-in` and `DELETE …/connection`. The code is redeemed as a confidential client at the `organizations` authority, the tenant comes from the `id_token` `tid`, both site scopes must be granted, and the delegated token is stored encrypted.
- Changed: `README.md` connect flow, and `api/developer_docs/operations-v1.json` with the two new operations.
- Verified: 16 new tests in `api/tests/integration/test_onedrive_sync_connection.py`, including a state issued to another user, Organization or purpose, a Member, a read-only API key, missing tenant or scope, Microsoft refusal and outage, replacing a pending connection and refusal while active.
- Follow-up: the site picker, the site grant and the "Agent Barn" folder.

### 2026-10-14 — AF-383 — Status, authorize URL and callback

- Delivered: `OneDriveSyncService` and routes in `api/domains/onedrive_sync/`, registered in `api/api_app.py`.
  - Status reports `available: false` when the platform app is unset, and hides a pending connection whose sign-in expired.
  - `authorize-url` returns 503 when unset and 409 for a connect while active or a disconnect while not.
  - The callback continues from admin consent to sign-in without trusting the redirect's `tenant`, and explains when a Microsoft Global Administrator must approve.
- Changed: `docs/features/onedrive-sync/README.md` (new feature doc), `docs/INDEX.md`, the `CONTEXT.md` link, and `api/developer_docs/operations-v1.json` with the three new operations.
- Verified: `api/tests/integration/test_onedrive_sync_connection.py` (21 tests) and `test_public_api_contract.py`.
- Follow-up: the read-only API key check moves to the sign-in POST, the first mutating route; `authorize-url` is a GET, which read-only keys may call.

### 2026-10-14 — AF-383 — Connection model, migration, repository and lookup

- Delivered: `api/domains/onedrive_sync/` (`models.py`, `repository.py`, `lookup.py`) and migration `734b0f2b3793_add_onedrive_sync_connection.py`, registered in `api/migrations/env.py`.
- Changed: `CONTEXT.md` defines OneDrive Sync Connection.
- Verified: `api/tests/integration/test_onedrive_sync_repository.py` (14 tests) covers the repository transitions, the one-open-row index, the Organization delete cascade and the lookup. A one-off autogenerate comparison found no drift between the model and the migration.
- Follow-up: status, authorize-url and callback routes.

### 2026-10-14 — AF-383 — Graph site search, site lookup and folder

- Delivered: `search_sites`, `get_site` and `ensure_folder` on `MicrosoftGraphSites` in `api/domains/agents/microsoft_graph_sites.py`, reusing its existing request helper and exceptions.
- Verified: new unit tests in `api/tests/unit/test_microsoft_graph_sites.py` cover the request URLs (URL-encoded search term and folder name), result parsing, reuse of an existing folder, creation of a missing one, a folder created in between, refusal, throttling and a response without a link.
- Follow-up: the `onedrive_sync` domain model, migration, repository and lookup.

### 2026-10-14 — AF-383 — Confidential client and consent state

- Delivered: optional `client_secret` on `MicrosoftIdentityClient.exchange_code` and optional `state` on `build_app_permission_consent_url` in `api/domains/agents/microsoft_identity.py`.
- Verified: new unit tests in `api/tests/unit/test_microsoft_identity.py`; the existing exact-request test still proves the public-client exchange sends no secret; `test_sharepoint_sign_in.py` and `test_sharepoint_selected_sites.py` pass unchanged.
- Follow-up: Microsoft Graph site search, site lookup by id, and folder creation.

### 2026-10-14 — AF-383 — Deploy wiring

- Delivered: `onedriveSyncClientId` / `onedriveSyncClientSecret` in `helm/agentbarn-api/values.yaml` and `templates/secret.yaml`, the matching `helmfile.yaml.gotmpl` values, and the variable and secret in `deploy.yml` and `deploy-public.yml`, shared across environments like the Google OAuth client.
- Changed: `docs/guidelines/operations.md` lists the OneDrive sync Microsoft app among the shared staging and public references.
- Verified: `helm template` of the API chart renders both keys when set and blank when unset.
- Follow-up: Microsoft identity support for a confidential client and consent `state`.

### 2026-10-14 — AF-383 — Platform app settings

- Delivered: `onedrive_sync_client_id`, `onedrive_sync_client_secret` and `is_onedrive_sync_enabled` on `Config`, with unit coverage in `api/tests/unit/test_config_onedrive_sync.py`.
- Changed: optional OneDrive sync blocks in `.env.spec` and `.env.deploy.spec`, naming the redirect URI `<WEB_APP_URL>/api/v1/integrations/onedrive-sync/callback` and the required Microsoft Graph permissions.
- Follow-up: deploy wiring.

### 2026-10-14 — AF-383 — Microsoft flow verification (no code)

- Verified by hand (browser and PowerShell) against a test SharePoint site, using a multi-tenant app with application `Sites.Selected` and delegated `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`:
  - Admin consent at `/organizations/v2.0/adminconsent` with `.default` succeeded once a Microsoft Global Administrator approved it. A non-admin gets Microsoft's "Need admin approval" page.
  - T-5: signing in at `/organizations/oauth2/v2.0/authorize` after consent showed only the account picker, with no second consent prompt.
  - A confidential-client code redemption returned tokens; the tenant came from the `id_token` `tid`.
  - The delegated token resolved the site and created a `write` site permission for the app.
  - T-1: an app-only token in that tenant created the "Agent Barn" folder in the site's default library and uploaded a file into it. The folder `webUrl` has the form `https://<tenant>.sharepoint.com/sites/<site>/Shared%20Documents/Agent%20Barn`.
- Follow-up: the connect UI must say that approving the app needs a Microsoft Global Administrator or Privileged Role Administrator.
