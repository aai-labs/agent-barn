# Sync providers — change log

Status: Active
Epic: AF-383 — Connect an Organization to OneDrive; AF-384 — Two-way file sync
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
  - the `file_sync` capability on the plugin seam, implemented by OneDrive, and a test-only `file_sync` provider.

  Nothing calls them yet, and no file syncs yet.
- Next, in this order, each as its own slice. Each slice adds the repository queries it uses.
  1. folder reconciliation;
  2. the Sync Engine and its deployment;
  3. Ingest file-sync routes;
  4. remote change processing;
  5. the in-pod helper;
  6. builder and `start.sh` wiring;
  7. pinned-image contracts;
  8. disconnect;
  9. docs consolidation;
  10. an end-to-end run on local k3d against the test tenant.
- Docs owed by the slice that makes them true:
  - **this README:**
    - the "Agent file sync" section, with folder reconciliation;
    - the Organization Member visibility limit, with the helper wiring;
    - the disconnect section, with disconnect;
  - **RBAC brief:**
    - the Sync Engine as background work;
    - Ingest file-sync traffic, alongside the memory gateway paragraph;
    - the visibility limit;
  - **[Agents](../agents.md):** delete stops sync, and a restore is followed on the next start;
  - **[activity and ingest](../activity-and-ingest.md):** the new routes;
  - **[runtime and deployment](../../architecture/runtime-and-deployment.md):** the engine and the new start step;
  - **[operations](../../guidelines/operations.md):** the Make target and Helm values;
  - **[INDEX](../../INDEX.md):** the new domain, engine and helper.
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

## Changes

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
