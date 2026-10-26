# Sync providers

## Read when

Read before changing how an Organization connects a storage provider (OneDrive today), the `sync_provider` domain or a Sync Provider Plugin, the provider callback, the Sync section in Organization settings, the platform Microsoft app settings, or Agent file sync (`file_sync` domain and the Sync Engine).

## Role in the system

An Organization Owner or Admin connects a storage provider once from Organization settings. Agent Barn is given access to one location at that provider and keeps an "Agent Barn" folder there, which every Organization Member can open. This is an Organization resource, not an [Integration](../integrations.md): no Agent is given the provider's credentials. Inside it, [Agent file sync](#agent-file-sync) keeps one folder per Agent.

Providers are plugins of one seam, the way messaging platforms are Platform Plugins of Communications ([ADR](../../adr/2026-10-16-sync-provider-plugin-seam.md)):

- The generic `SyncProviderService` (`api/domains/sync_provider/`) owns permissions, the signed state, the callback page, the connection lifecycle, and one connection at a time.
- Each `SyncProviderPlugin` (`api/domains/sync_provider/plugins/`) talks only to its provider: sign-in, location search, provisioning and its rollback, and revoking. It depends only on its provider's HTTP clients, never on another domain's services or repositories, and never touches the database. OneDrive reuses the Microsoft identity and Graph clients in `api/domains/agents/` (`microsoft_identity.py`, `microsoft_graph_sites.py`, and `microsoft_graph_files.py` for file sync), the first two shared with the SharePoint integration.

Delivery state is tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Provider list and routes

- `GET /organizations/{organization_id}/sync-providers` requires `organization.read`, so every Organization Member sees the folder link. It has one entry per provider shipped with Agent Barn, in key order, including providers not set up on this server:
  - the descriptor: `key`, `display_name`, `tagline`, `folder_hint`, `connect_hint`, `location_noun`, `schema_version`, `capabilities`;
  - `available`, false when the provider's server settings are blank. An unavailable provider has no `approval_url` or `blocked_reason`, and `can_connect` is false;
  - `approval_url`;
  - `connection`: status, location name and URL, folder link and connected time, or `null`;
  - `can_connect` and `blocked_reason`.
- Every route under `…/sync-providers/{provider_key}/connection` requires `organization.update`. An unknown provider, or one whose settings are blank (not offered), is 404.
- A caller outside the Organization gets 403, like every Organization-scoped route; 404 concealment applies to Agent resources only.
- The list never includes tokens, the provider account or provider data. A pending connection whose sign-in has expired reads as not connected.
- Connections are stored in `sync_provider_connection`, keyed by `provider_key`, with the plugin's `schema_version`. Disconnected rows are kept; rows cascade on Organization delete.
- The callback (`GET /api/v1/integrations/sync-provider/{provider_key}/callback`) is unauthenticated. It trusts only state this server signed with type `sync_provider_state` for that provider: a SharePoint or Google state, or another provider's, is refused.

## Connection lifecycle

Paths below are relative to `/organizations/{organization_id}/sync-providers/{provider_key}`.

1. The UI opens a popup and calls `GET …/connection/authorize-url?purpose=connect`. It is refused with 409 while this provider is active or another provider blocks it (see below).
2. The server signs a state (Organization, user, provider, purpose, encrypted PKCE verifier, 10-minute expiry) and returns the plugin's sign-in URL with the PKCE challenge.
3. The provider redirects to the callback. The callback reads `error` first and posts the plugin's message for it. A plugin with `admin_approval` can recognise an approver returning; the callback then shows "Agent Barn is approved for your organization. The person connecting can now connect {provider}." After a sign-in, the callback posts `{type: "sync-provider-oauth", code, state}` to the opener.
4. The opener calls `POST …/connection/sign-in {code, state}`. A read-only API key is refused, as on any mutating route. The server:
   1. requires a connect state issued to this caller for this Organization and provider (400 otherwise);
   2. has the plugin redeem the code;
   3. stores a pending connection holding the delegated token Fernet-encrypted (`AGENT_TOKEN_ENCRYPTION_KEY`) until the token expires. A new sign-in replaces this provider's pending connection; another provider's expired sign-ins are cleared.

   A provider without `location_picker` is provisioned straight away, and the connection becomes active. If provisioning fails, the pending connection is removed.
5. With `location_picker`:
   - `GET …/connection/locations?search=<term>` searches with the delegated token. The term is required.
   - `POST …/connection/location {location_id}`:
     1. reads the location from the provider, so its name and URL never come from the client;
     2. runs the plugin's location guard, if it declares one (409, before anything is granted);
     3. provisions, then activates the connection with the location, the folder link and the plugin's `provider_data`, and drops the delegated token.

   Searching or choosing without a fresh pending connection is 409: the person connects again.
6. `DELETE …/connection` abandons a pending connection and leaves an active one alone.
7. Disconnect:
   1. `GET …/connection/authorize-url?purpose=disconnect` (409 unless active) returns the sign-in URL.
   2. `POST …/connection/disconnect {code, state}` requires a disconnect state for this caller, Organization and provider (400), and an active connection (409).
   3. The plugin redeems the code and requires the same account that connected.
   4. Holding the connection's Sync Engine lock (`FileSyncFolderRemoval`), it waits up to 15 s for a running engine pass. If the lock isn't free by then, the answer is 409 "File sync is busy with this connection. Try again in a moment." and nothing changes.
   5. Every Agent Folder, including disabled ones and retired ones still waiting to be deleted, is deleted at the provider with Agent Barn's own access, and its row is removed, together with its `sync_file` rows. A folder already gone at the provider is skipped. `sync_activity` keeps its history, with `folder_id` cleared.
   6. The plugin revokes Agent Barn's access with the fresh sign-in.
   7. The connection is marked disconnected. The "Agent Barn" root folder is left in place, and the Organization may connect again. Agents' volumes and pods are not touched.

   If a provider call fails at step 5 or 6, the connection stays active. The next engine pass gives every Agent without a folder a new one, and their pods upload their files again.

Plugin failures map to HTTP the same way for every provider:

| Failure | Status |
|---|---|
| `SignInRefused`, `SignInIncomplete`, `LocationNotFound` | 400 |
| `LocationAccessRefused` | 403 |
| `ProviderUnavailable`, `ProvisioningFailed` | 502 |
| `ProviderThrottled` | 503 |

The message is the plugin's own.

## One connection at a time

An Organization has at most one open (pending or active) connection across all providers. Two places enforce it:

- `SyncProviderService._blocking_connection`. While another provider is connected, starting or completing a connect returns 409 "Disconnect OneDrive first." While another provider is pending, the message is "Finish connecting OneDrive, or start over, first." The list reports the same text as `blocked_reason`, with `can_connect: false`. Another provider's expired sign-in doesn't block.
- The partial unique index `uq_sync_provider_connection_open` on `organization_id`.

The UI holds no rule of its own; it renders `can_connect` and `blocked_reason`.

**Changing to several providers at once:** remove `_blocking_connection` and its use, add a migration that replaces the index with one on `(organization_id, provider_key)`, and rewrite the "one connection at a time" groups in `test_sync_provider_connection.py` and `test_sync_provider_repository.py`. Routes, the list shape, repository queries and the UI stay as they are.

## Organization settings

Settings → **Sync** (`?tab=sync`) is visible to every Organization Member. It reads the provider list and shows one row per offered provider (`ui/src/features/sync-provider/`). The UI has no provider-specific branches: every text it shows about a provider comes from the provider's entry.

- A provider not set up on this server (`available: false`) shows "{provider} is not configured for the platform." and no buttons, the same for every role.
- No providers at all: "No sync providers are available on this server."
- Each row has the provider's brand mark (OneDrive's logo; a letter tile for a provider without one), the provider's name, and a subtitle: its `tagline`, "Connecting…" while pending, or "● Connected to {location}" in green when active.
- Not connected:
  - Owners and Admins get **Connect**. It opens the provider's sign-in popup and then posts the code to the sign-in route. Connect is enabled only when `can_connect` is true:
    - when it's false, the row shows `blocked_reason`;
    - otherwise it shows the provider's `connect_hint`.

    When the provider has `approval_url`, the row offers it as the **approval link** to forward. A provider error from the callback is shown inline.
  - Members are told an Owner or Admin can connect.
- Pending:
  - Owners and Admins of a provider with `location_picker` get the picker inline: a search that needs a term (labelled from `location_noun`), a result list, and **Use**. The API's `detail` is shown inline when choosing fails. Reloading the page resumes at the picker while the sign-in is fresh. **Start over** abandons the unfinished connection.
  - Members are told no {location_noun} has been chosen yet.
- Active: **Open in {provider}** links to the folder in a new tab, with the provider's `folder_hint` underneath. Owners and Admins also get **Disconnect**, confirmed in a dialog. For a provider with `file_sync` it says each Agent's folder is deleted first, and that the "Agent Barn" folder and the Agents' own files stay. For any other provider it says the folder and its files stay where they are. It then opens the sign-in popup and posts the code to the disconnect route. A refusal is shown inline and the connection stays.
- Connecting or disconnecting one provider refetches the list, because it changes whether the others may connect.

The query is keyed by Organization id, so switching Organization never shows the previous one's providers.

## Adding a provider

A new provider is a plugin, its provider client, and tests. No route, table, migration or UI change is needed.

1. **Settings.** Add its settings to `api/core/config.py` and wire them like `ONEDRIVE_SYNC_CLIENT_ID/SECRET`: the `.env` specs, the API chart, Helmfile, the deploy workflows and [operations](../../guidelines/operations.md). `is_offered()` returns whether they are set; while they are blank the provider is listed as not configured. Add a self-hosting step to the root `README.md`, like "Connecting OneDrive (manual step)".
2. **The plugin.** Write `api/domains/sync_provider/plugins/<key>.py`, subclassing `SyncProviderPlugin`:
   - `key`, `display_name`, `tagline`, `folder_hint`, and optionally `connect_hint`;
   - `authorize_url`, `complete_sign_in`, `require_same_account`, `provision`, `undo_provision` and `revoke`, raising the typed failures from `base.py`.
3. **Capabilities.** Declare only what it implements:
   - `location_picker` needs `search_locations`, `resolve_location` and a `location_noun`;
   - `admin_approval` needs `approval_url` and `is_approval_callback`;
   - `file_sync` needs `create_folder`, `get_item`, `get_item_by_path`, `move_item`, `delete_item`, `changes`, `upload_target`, `download_url` and `write_empty_file`. They act as Agent Barn under the connection's `SyncRoot`, report paths relative to the "Agent Barn" folder in `RemoteItem`, and raise `RemoteItemMissing`, `RemoteNameTaken`, `RemoteChangeRejected`, `RemoteResyncRequired`, or `ProviderThrottled` with `retry_after`. The upload and download URLs must work without any provider credential, because the Agent's pod uses them.

   The registry refuses a plugin that declares a capability without its methods.
4. **Guards.** A check owned by another domain is declared as a `SyncLocationGuard` member and bound in `SyncProviderService._guard`. The plugin never imports that domain.
5. **Register it.** Add it to `shipped_plugins` in `plugins/providers.py`. The contract sweep in `api/tests/unit/test_sync_provider_plugins.py` then covers it. Add unit tests for its provider requests and failure mapping.
6. **Redirect URI.** Register `<WEB_APP_URL>/api/v1/integrations/sync-provider/<key>/callback` with the provider.
7. **Optional brand mark.** Add ui/public/brand/<key>.svg and a case in syncProviderIcon (ui/src/components/brand-icons.tsx); until then the UI shows a letter tile.

## Agent file sync

Decided in the [Agent file sync ADR](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md). Every Agent gets its own folder inside "Agent Barn", and the Agent's files are kept in sync with it both ways. The Agent's version is the source of truth: people may edit the Agent's work and memory there, and every other change a person makes is undone.

There are three parts:
- the Sync Engine, which follows the provider;
- the pod helper, which follows the Agent's volume;
- the [Ingest file sync routes](../activity-and-ingest.md) between them, which own the pod-facing contract.

The provider's credentials never enter a pod; the pod only ever holds per-file upload and download links. The end-to-end run against a real tenant is tracked in [`CHANGELOG.md`](CHANGELOG.md).

### What syncs

Paths are relative to the runtime's root: `/opt/data` for Hermes, whose `workspace/` is the Agent's `/workspace`, and `/home/node/.openclaw` for OpenClaw. `api/domains/file_sync/rules.py` is the one source. It ships to pods as `file-sync-rules.json`, and Ingest checks every path against it again.

| Category | Hermes | OpenClaw | A person's edit at the provider |
|---|---|---|---|
| `config` | `SOUL.md`, `workspace/IDENTITY.md`, `AGENTS.md`, `TOOLS.md`, `BOOT.md`, `HEARTBEAT.md` | `workspace/SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `TOOLS.md`, `BOOT.md`, `BOOTSTRAP.md`, `HEARTBEAT.md` | Undone |
| `skills` | `workspace/skills/**` | `workspace/skills/**` | Undone |
| `memory` | `memories/USER.md`, `memories/MEMORY.md` | `workspace/USER.md`, `workspace/MEMORY.md` | Applied to the Agent |
| `work` | Everything else under `workspace/` | Everything else under `workspace/` | Applied to the Agent |
| `never` | Everything else | Everything else | — |

`never` covers credentials and runtime machinery (`config.yaml`, `openclaw.json`, `.env`, `aai-cli/`, sessions), and also, anywhere:
- `.git/`, `node_modules/` and `__pycache__/`;
- `_Not synced/`;
- symlinks and anything behind them;
- the helper's own `.file-sync-` temporary files.

`config` files are rebuilt from the Template at every start, and `skills` from the Agent's skills, so they are mirrored read-only.

### How fast changes travel

- **An Agent's change reaches the provider** on the helper's next round. Rounds run every 15 s, and a file still being written waits 5 s. Then the file uploads.
- **A person's change reaches the Agent, or is undone,** in at most about 75 s plus the transfer:
  1. the Sync Engine sees it on its next pass (every 30 s);
  2. the job waits until 30 s after the item's last change, so autosave settles;
  3. the helper picks it up on its next round (every 15 s).
- **A stopped Agent** gets its waiting jobs in the helper's run before the runtime starts.

### The Agent's pod

Every Hermes and OpenClaw ConfigMap carries `file-sync.py` and `file-sync-rules.json`, which is `rules_manifest` for that runtime. After the Template files and skills are written, `start.sh` runs the helper once, bounded at 60 s and never failing the start, then keeps it running every 15 s while the runtime starts.
- **Each round:** it scans the synced paths, reports them, uploads what the server asks for, and applies its download and re-upload jobs.
- **Files being written:** in the background loop, a file changed within the last 5 s keeps its last reported version, or is left out and the report marked incomplete. The run before start skips this wait, because the runtime is not yet writing, so the files `start.sh` has just written are offered at once.
- **When it stops:** a refused key (401) stops it. An Agent without an active folder gets 404 or 409 and keeps asking, so sync starts once a connection is made. An Agent whose File Sync switch is off gets 409 on every round, so its Logs show `[file-sync] ingest answered 409` every 15 s until the switch is turned on.
- **No provider credentials:** the pod only ever holds per-file upload and download links.

### Sync Engine

The Sync Engine (`api/sync_engine_main.py`, `make dev-sync-engine`, chart value `syncEngine`) runs one pass every 30 s. A pass handles each active connection that has a root folder, whose provider declares `file_sync`, and that is not waiting out throttling.
- **Locking:** it holds that connection's advisory lock, and skips a connection another copy holds.
- **Throttling:** when the provider throttles, the connection waits until now plus the provider's `Retry-After` (`sync_retry_at`), or 60 s when none is given. Other connections go on.
- **Failures:** any other failure is logged, and the other connections still sync.
- **Heartbeat:** a completed pass refreshes the liveness heartbeat; a failed pass does not.

Its reads and writes are background work under the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md): unscoped, keyed by the connection's own Organization and id, and reachable from no router.

### Agent Folders

Every live Agent of the Organization whose [File Sync switch](#turning-sync-off) is on gets a folder directly under "Agent Barn", recorded in `sync_agent_folder`.
- **New Agents:** the row is reserved first, oldest Agent first, and the database's unique name index decides ties. The folder is then created at the provider. A failed create is finished on the next pass.
- **Renamed Agents:** their folder is renamed.
- **Retired (deleted) Agents:** their folder is marked `retired` and deleted at the provider (to its recycle bin), then its row is removed. Its `sync_file` rows go with it, and `sync_activity` keeps its history with `folder_id` cleared. Retiring has no undo in Agent Barn, so the provider's recycle bin is the only way back.
  - **Already gone:** a folder already gone at the provider just loses its row.
  - **Throttled:** the connection waits out `Retry-After`, the folder stays `retired`, and the next pass tries again.
  - **Other failures:** any other provider failure is logged, and the next pass tries again. Other Agents' folders are not held up.
  - **The change feed** later reports the deletion, which matches no row, so nothing is rebuilt.
- **Stopped Agents** (Stop, not Retire) keep their folder `active` and its files. Their jobs wait for the next start.
- **The File Sync switch:** an Agent whose switch is off gets no folder. Each pass also brings the folder in line with the switch, for the cases the switch's own request could not reach (the folder didn't exist yet when it was changed): an `active` folder whose switch is off becomes `disabled`, and a `disabled` folder whose switch is on becomes `active` with a re-check requested.
- **Disabled folders** are otherwise left alone: not renamed, and their files not synced. When no folder needs changing, this part of the pass makes no provider call.

Folder names follow the Agent's name:
- `: " * < > ? | \ /` and control characters become `-`;
- spaces are trimmed at both ends, and dots at the end;
- an empty name, or one the provider refuses (reserved names such as `CON`, or the `_vti_` prefix), becomes `Agent`;
- names are at most 255 characters, cut before a number is added.

Duplicate names, compared case-insensitively, get the lowest free ` (2)`, ` (3)`…
- **Taken names:** names of disabled folders stay taken, and so do names already used at the provider. Retired folders are deleted before names are given out, so a new Agent named like a retired one gets the plain name, or a number while the old folder's deletion is still pending.
- **Dropping the number:** a numbered folder drops its number once the plain name is free. Two Agents swapping names therefore settle within two passes without ever sharing a name.

### People's edits

After the folders, each pass reads the provider's changes under "Agent Barn" since the connection's `sync_cursor`. That is one provider call per page, and normally one per pass.
- **Starting point:** a connection's first pass only records a cursor starting now, so files already there are not treated as edits.
- **Saving progress:** the cursor is saved after each page. A page interrupted by throttling or a failure is read again on the next pass; handling the same change twice does nothing more.
- **Expired cursor:** when the provider says the cursor is no longer valid (`RemoteResyncRequired`), the pass lists everything under "Agent Barn" from the start and handles each item as a change. Matching content versions mean no edit is invented. Afterwards:
  - an active Agent folder that was not listed is rebuilt;
  - a synced file not listed, in a folder that was, is restored from the Agent;
  - the cursor from the end of the listing is saved, but only then, so an interrupted listing starts again.
- **Stopped Agents:** their jobs wait in `sync_file` until the pod asks for them.

A changed item is matched to its Agent Folder by its first path segment, and to its `sync_file` row by the provider's item id, across every folder of the connection.
- **Always ignored:** changes the provider attributes to an app, which includes the engine's own moves and renames, and anything inside `<Agent>/_Not synced/`.
- **Inactive folders:** files in a folder that is not active are ignored.

Files a person adds, removes or moves:
- **A file the Agent does not have:** a new file anywhere in an Agent's folder is moved to `<Agent>/_Not synced/` (created when missing), and `moved_not_synced` is recorded. A name already taken there gets ` (2)`, ` (3)` before its extension.
- **A new file at a synced path,** such as one deleted and added again, is taken as an edit of that file, unless the Agent's own upload of that path is under way.
- **A synced file deleted,** or moved out of "Agent Barn", into `_Not synced/` or into another Agent's folder: it is restored from the Agent (a `reupload` job, with the row's provider fields cleared). `restored` is recorded when the Agent's copy is back. A file that lands in another Agent's folder is moved to that folder's `_Not synced/`.
- **A synced file renamed or moved within its folder:** it is moved back to its path, and `renamed_back` is recorded. If the way back is blocked, it is restored instead and the moved copy is parked in `_Not synced/`.

Agent folders:
- **Renamed or moved:** an Agent's folder is put back under "Agent Barn" with its name.
- **Deleted:** its folder id is cleared, so the next pass creates it again, and every file it held gets a `reupload` job.
- Both record `folder_restored`.

A file whose path and row match is a content edit. It is ignored when an upload of it is under way, or its content version equals the one recorded. Otherwise a person changed its content:
- **Work and memory files:** a `download` job for the pod. An edit over 100 MB is not downloaded, and is recorded once as `skipped_too_large`.
- **Config and skills files:** a `reupload` job, which undoes the edit with the Agent's copy. `edit_undone` is recorded when the Agent's copy is back, once per undo, however many edits it threw away.
- **Autosave:** a job is not handed out until 30 s after the item's last modification (`retry_at`). Each further autosave pushes that back, and the cursor never waits.
- **One job per file:** a pending re-upload is never turned into a download.

### The Agent's own changes

The pod reports its full file list, and Ingest answers with upload links. The [Ingest contract](../activity-and-ingest.md) owns the details:
- **New and changed files** are uploaded and then confirmed; the server checks each confirmation at the provider.
- **Empty files** are written by the server.
- **Deletes:** a file missing from a complete report is deleted at the provider (its recycle bin).
- **Conflicts:** when the Agent changed a file a person also edited, the Agent wins. Its version is uploaded over the person's, which stays in the provider's version history, and `conflict_agent_won` is recorded.

The helper never deletes a file on the volume.

### Turning sync off

Each Agent has a File Sync switch, `agent.file_sync_enabled`, on by default. It can be set when the Agent is created ([Agents](../agents.md#create)), and changed at any time with `PUT /organizations/{organization_id}/agents/{agent_id}/file-sync {enabled}`:
- **Permission:** `agent.update`. An invisible, other-Organization or deleted Agent is 404; a visible one without the permission is 403; a read-only API key is refused.
- **Answer:** 200 `{agent_id, enabled}`. Setting the value it already has changes nothing and records nothing.
- **In the same transaction:**
  - the Agent's folder on the Organization's active connection, if there is one, becomes `disabled` (off), or `active` with `resync_requested_at` set (on);
  - `agent.file_sync.disabled` or `agent.file_sync.enabled` is recorded for the security audit ([Domain Events](../domain-events.md)).
- **While the switch is off:** the pod is refused (409) on every route, even before the folder is `disabled` and even when there is no folder. An Agent without a folder doesn't get one, and the Sync Engine marks a folder it still finds `active` as `disabled` on its next pass ([Agent Folders](#agent-folders)).
- **While the folder is `disabled`:** the pod is refused (409), the Sync Engine leaves the folder and its files alone, and the folder and everything in it stay at the provider. The folder's name stays taken.
- **A restore** of an Agent Restore Point doesn't change the switch.

### Activity

Everything File Sync does that a person should be able to see is stored in `sync_activity`, at the time it actually happened: the Organization, Agent, folder, kind, path, detail and time. Rows are kept after their folder is removed, with `folder_id` cleared, and for now they are kept forever. No route or UI reads them yet; the agent page card is the next ticket.

| Kind | Meaning |
|---|---|
| `edit_undone` | A person edited a `config` or `skills` file; the Agent's copy was put back. |
| `restored` | A person deleted or moved away a synced file; the Agent's copy was put back. |
| `renamed_back` | A person renamed or moved a synced file within its folder; it was moved back. |
| `moved_not_synced` | A person added a file the Agent does not have; it was moved to `_Not synced/`. |
| `folder_restored` | A person renamed, moved or deleted an Agent's folder; it was put back or rebuilt. |
| `conflict_agent_won` | The Agent changed a file a person had also edited; the Agent's version was kept. |
| `deleted_by_agent` | The Agent deleted a file; it was deleted at the provider. |
| `skipped_too_large` | A file over 100 MB, on either side, was not synced. |
| `skipped_name` | A name the provider refuses, a path over its 400-character limit, or a path differing only in case from another was not synced. |
| `skipped_no_space` | The Agent's volume had no room for a person's edit; it is retried. |

### Limits

- **Size and names:** files over 100 MB are not synced. Neither are names the provider refuses, paths whose full provider path exceeds 400 characters, or a second path differing from another only in case. Each is recorded once as a skip.
- **What the helper skips:** names not in Unicode NFC form, and paths over 1,024 characters.
- **Large file lists:** the helper reports at most 10,000 files. Beyond that, the report is incomplete, so files the Agent deleted are not deleted at the provider.

### Known limits of file sync

- **Every Organization Member can open the Agent Folders,** and can edit work and memory files there, including Members without Agent Access to that Agent. This is accepted in the ADR and recorded in the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md).
- **Deleting the "Agent Barn" folder itself is not handled.** The change feed is anchored to that folder, and what the provider then returns is unverified.
- **Stopped Agents:** undos, restores and people's edits wait for the Agent's next start, with no time limit. The Agent then gets each file's latest version.
- **Conflicts keep the Agent's version.** The person's edit survives only in the provider's version history.
- **Running Agents** start syncing after their next restart or managed update.
- **Pods ask Ingest every 15 s** even when their Organization has no connection, so that sync starts as soon as one is made.

## OneDrive provider

`OneDriveSyncProviderPlugin` (key `onedrive`) connects OneDrive through one SharePoint site. Agent Barn's multi-tenant Microsoft app is granted `write` on the chosen site with `Sites.Selected`, and creates the "Agent Barn" folder in the site's default document library as the app. Capabilities: `location_picker` (`location_noun` "SharePoint site"), `admin_approval` and `file_sync`. Location guard: `SHAREPOINT_AGENT_SITES`. File sync acts as the platform app in the connection's tenant, with an app-only token cached per tenant (`MicrosoftAppTokens`).

### Platform app

`ONEDRIVE_SYNC_CLIENT_ID` and `ONEDRIVE_SYNC_CLIENT_SECRET` configure one multi-tenant Microsoft Entra app ([operations](../../guidelines/operations.md)). Its Web redirect URI is `<WEB_APP_URL>/api/v1/integrations/sync-provider/onedrive/callback`; Microsoft accepts plain `http` only for `localhost`. Permissions:

- Application: `Sites.Selected`.
- Delegated: `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`.

When either setting is blank, OneDrive is listed as "OneDrive is not configured for the platform." and its routes return 404 "OneDrive isn't available on this server." Self-hosters set it up following "Connecting OneDrive (manual step)" in the root [`README.md`](../../../README.md#connecting-onedrive-manual-step). The secret is never returned or logged.

### Microsoft specifics

- **Approving the app (once per Microsoft organization).** A Microsoft Global Administrator or Privileged Role Administrator approves the app. `approval_url` is Microsoft's admin-consent link at the `organizations` authority with `scope=https://graph.microsoft.com/.default` and no state. Microsoft returns to the callback with `admin_consent=True`. After approval, connecting needs no Global Administrator.
- **Sign-in** is at the `organizations` authority with `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile` and `prompt=select_account`; there is no consent step.
  - Where the app isn't approved yet, Microsoft reports `consent_required` or AADSTS65001/65004/90094/90095. The callback then shows "A Microsoft Global Administrator needs to approve Agent Barn for your organization."
  - The code is redeemed as a confidential client (the platform secret plus the PKCE verifier).
  - The tenant comes from the `id_token`'s `tid` (400 if missing) and is stored as the connection's `account_id`. It is never taken from Microsoft's admin-consent redirect, which an attacker can alter, and the callback never echoes it.
  - Both `Sites.FullControl.All` and `Sites.Read.All` must be granted (400 otherwise). No refresh token is requested.
- **Locations** are SharePoint sites: Graph's site search with the administrator's delegated token. Microsoft doesn't document what an empty search returns, so a term is required.
- **Provisioning:**
  1. grants the platform app `write` on the site, with display name "Agent Barn", using the administrator's delegated token. Microsoft requires the signer to be a SharePoint Administrator and a member of the site, so a refusal is a 403 that says so;
  2. gets an app-only token in the connection's tenant;
  3. ensures the "Agent Barn" folder at the root of the site's default document library;
  4. stores the grant id in `provider_data` (`permission_id`).

  If the app token or the folder fails, the grant is revoked with the delegated token and the connection stays pending (502). Throttling is 503.
- **Disconnect:**
  - Revoking the grant needs the administrator's delegated `Sites.FullControl.All`, because an app granted `write` cannot manage site permissions.
  - The sign-in's `tid` must equal the connection's tenant, compared case-insensitively (400 "Sign in with an account from the Microsoft organization that connected OneDrive.").
  - A refused revoke is 403 (SharePoint Administrator and site member), throttling 503, an unreachable Microsoft 502. In all three cases the connection stays active.

### Keeping Agents out of the folder site

- **Connecting refuses a site an Agent holds.** If any Agent in the Organization, including a deleted one, holds a recorded SharePoint selected-sites grant on the site id (compared case-insensitively), choosing it is refused with 409: "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick another site."
  - Deleting an Agent neither revokes nor forgets its grants, so they still count.
  - This is the `SHAREPOINT_AGENT_SITES` guard, bound to `SharePointService.organization_site_ids`.
- **The SharePoint integration refuses the folder site.** It won't grant an Agent the site holding the Organization's folder (409, before any grant), through `SyncProviderLookupService.sharepoint_folder_site_id(organization_id)`: the active connection's location when its provider declares the `SHAREPOINT_AGENT_SITES` guard. SharePoint never names a provider. See [SharePoint selected sites](../integrations.md#sharepoint-selected-sites).
- **Delegated-mode SharePoint Agents are not guarded.** They have no per-site grant, so they reach whatever the person who signed them in can open, which may include the folder site. This gap is accepted and documented, not enforced.

### Known limits

- **Delegated-mode SharePoint Agents** can reach the folder site through their signer's own access; only selected-sites grants are guarded.
- **Deleting an Organization** deletes its connection row (cascade) but leaves the platform app's grant on the site in Microsoft. Nobody is signed in to revoke it. An administrator can remove it from the site's permissions.
- **There is no lock between an Agent's selected-sites grant and an Organization connecting at the same moment.** Each check reads the other's state independently, so two requests finishing together can both pass.
- **Approving the app needs a Microsoft Global Administrator or Privileged Role Administrator**, once per Microsoft organization, and again only if the app's permissions change. Connecting and disconnecting need a SharePoint Administrator who is a member of the site.
- **The app shows as "unverified" on Microsoft's consent page** until AAI Labs completes [publisher verification](https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview). A Global Administrator can still approve it, because the app needs admin consent anyway. Organizations whose user-consent policies only allow verified publishers will still see the unverified label. Verification needs a verified AAI Labs AI Cloud Partner Program partner global account, a publisher domain that isn't `*.onmicrosoft.com`, and someone who is both an Entra Application Administrator and a Partner Center admin, signing in with MFA. It has no cost.

## Source map

| Concern | Source |
|---|---|
| Plugin seam, registry and shipped plugins | `../../../api/domains/sync_provider/plugins/base.py`, `registry.py`, `providers.py`; registered in `../../../api/infrastructure/app.py` |
| OneDrive plugin and settings | `../../../api/domains/sync_provider/plugins/onedrive.py`, `../../../api/core/config.py` (`is_onedrive_sync_enabled`) |
| Persistence and read contracts | `../../../api/domains/sync_provider/models.py`, `repository.py` |
| Flow, state, callback page, guards, one at a time | `../../../api/domains/sync_provider/service.py` |
| Routes | `../../../api/domains/sync_provider/routes.py` |
| Folder location for other domains | `../../../api/domains/sync_provider/lookup.py`, used by `../../../api/domains/agents/sharepoint_service.py` |
| Microsoft identity and Graph calls | `../../../api/domains/agents/microsoft_identity.py`, `microsoft_graph_sites.py` |
| UI | `../../../ui/src/features/sync-provider/`, registered as `sync` in `../../../ui/src/features/organizations/components/organization-settings-utils.ts` and `../../../ui/src/app/dashboard/[orgId]/settings/page.tsx` |
| Agent file sync: rules, models, engine pass, Ingest service and routes, folder removal on disconnect, the per-Agent switch | `../../../api/domains/file_sync/` (`rules.py`, `models.py`, `engine.py`, `repository.py`; `ingest_service.py` and `ingest_routes.py` for the pod, registered in `../../../api/ingest_app.py`; `service.py` and `routes.py` for folder removal and the switch, registered in `../../../api/api_app.py`) |
| Pod helper and its start | `../../../api/domains/agents/scripts/file-sync.py`, shipped by `../../../api/domains/agents/builders/hermes.py` and `openclaw.py`, started by both runtimes' `start.sh` |
| Sync Engine process and deployment | `../../../api/sync_engine_main.py`, `../../../helm/agentbarn-api/templates/sync-engine-deployment.yaml` |
| Microsoft file calls and app-only tokens | `../../../api/domains/agents/microsoft_graph_files.py`, `MicrosoftAppTokens` in `microsoft_identity.py` |
| Tests | `../../../api/tests/unit/test_sync_provider_plugins.py`, `../../../api/tests/integration/test_sync_provider_connection.py`, `test_sync_provider_repository.py`, `../../../api/tests/steps/sync_provider.py` (test-only second provider), `../../../ui/tests/e2e/sync-provider.spec.ts`; file sync: `../../../api/tests/integration/test_file_sync_*.py`, `../../../api/tests/unit/test_file_sync_rules.py`, `test_file_sync_helper.py`, `test_microsoft_graph_files.py`, `test_test_drive_file_sync.py`, `test_sync_engine_main.py`, `../../../api/tests/steps/file_sync_provider.py` (test-only `file_sync` provider), `../../../api/runtime_tests/test_hermes_file_sync.py` and `test_openclaw_file_sync.py` (pinned images) |

## Change impact

- Changing the callback path, the state, or a provider's scopes affects that provider's app registration (redirect URI, permissions) in every environment.
- Changing the one-open-connection rule needs a migration.
- Changing the provider list's shape affects the Sync UI and `api/developer_docs/operations-v1.json`.
