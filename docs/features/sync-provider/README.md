# Sync providers

## Read when

Read before changing how an Organization connects a storage provider (OneDrive today), the `sync_provider` domain or a Sync Provider Plugin, the provider callback, the Sync section in Organization settings, the platform Microsoft app settings, or Agent file sync (`file_sync` domain and the Sync Engine).

## Role in the system

An Organization Owner or Admin connects a storage provider once from Organization settings. Agent Barn is given access to one location at that provider and keeps an "Agent Barn" folder there, which every Organization Member can open. This is an Organization resource, not an [Integration](../integrations.md): no Agent is given the provider's credentials. Inside it, [Agent file sync](#agent-file-sync) keeps one folder per Agent.

Providers are plugins of one seam, the way messaging platforms are Platform Plugins of Communications ([ADR](../../adr/2026-10-16-sync-provider-plugin-seam.md)):

- The generic `SyncProviderService` (`api/domains/sync_provider/`) owns permissions, the signed state, the callback page, the connection lifecycle, and one connection at a time.
- Each `SyncProviderPlugin` (`api/domains/sync_provider/plugins/`) talks only to its provider: sign-in, location search, provisioning and its rollback, and revoking. It depends only on its provider's HTTP clients, never on another domain's services or repositories, and never touches the database. OneDrive reuses the Microsoft identity and Graph clients in `api/domains/agents/` (`microsoft_identity.py`, `microsoft_graph_sites.py`), which it shares with the SharePoint integration.

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
   3. The plugin redeems the code, requires the same account that connected, and revokes Agent Barn's access with that fresh sign-in.
   4. The connection is marked disconnected. The folder and its files are left in place, and the Organization may connect again.

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
- Active: **Open in {provider}** links to the folder in a new tab, with the provider's `folder_hint` underneath. Owners and Admins also get **Disconnect**, confirmed in a dialog that says the folder and its files stay where they are. It then opens the sign-in popup and posts the code to the disconnect route. A refusal is shown inline and the connection stays.
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

Decided in the [Agent file sync ADR](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md). Delivery is in progress, and this section describes only what runs today: each Agent's folder. Files are not synced yet ([`CHANGELOG.md`](CHANGELOG.md)).

### Sync Engine

The Sync Engine (`api/sync_engine_main.py`, `make dev-sync-engine`, chart value `syncEngine`) runs one pass every 30 s. A pass handles each active connection that has a root folder, whose provider declares `file_sync`, and that is not waiting out throttling.
- **Locking:** it holds that connection's advisory lock, and skips a connection another copy holds.
- **Throttling:** when the provider throttles, the connection waits until now plus the provider's `Retry-After` (`sync_retry_at`), or 60 s when none is given. Other connections go on.
- **Failures:** any other failure is logged, and the other connections still sync.
- **Heartbeat:** a completed pass refreshes the liveness heartbeat; a failed pass does not.

Its reads and writes are background work under the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md): unscoped, keyed by the connection's own Organization and id, and reachable from no router.

### Agent Folders

Every live Agent of the Organization gets a folder directly under "Agent Barn", recorded in `sync_agent_folder`.
- **New Agents:** the row is reserved first, oldest Agent first, and the database's unique name index decides ties. The folder is then created at the provider. A failed create is finished on the next pass.
- **Renamed Agents:** their folder is renamed.
- **Deleted Agents:** their folder is marked `stopped` without calling the provider, and stays at the provider with its files.
- **Disabled folders** are left alone. A pass with nothing to do makes no provider call.

Folder names follow the Agent's name:
- `: " * < > ? | \ /` and control characters become `-`;
- spaces are trimmed at both ends, and dots at the end;
- an empty name, or one the provider refuses (reserved names such as `CON`, or the `_vti_` prefix), becomes `Agent`;
- names are at most 255 characters, cut before a number is added.

Duplicate names, compared case-insensitively, get the lowest free ` (2)`, ` (3)`…
- **Taken names:** names of stopped and disabled folders stay taken, so a new Agent named like a deleted one gets a number. So do names already used at the provider.
- **Dropping the number:** a numbered folder drops its number once the plain name is free. Two Agents swapping names therefore settle within two passes without ever sharing a name.

A person renaming or deleting an Agent's folder, or the "Agent Barn" root, at the provider is not handled yet.

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
| Agent file sync: rules, models, folder pass, engine queries | `../../../api/domains/file_sync/` (`rules.py`, `models.py`, `engine.py`, `repository.py`) |
| Sync Engine process and deployment | `../../../api/sync_engine_main.py`, `../../../helm/agentbarn-api/templates/sync-engine-deployment.yaml` |
| Microsoft file calls and app-only tokens | `../../../api/domains/agents/microsoft_graph_files.py`, `MicrosoftAppTokens` in `microsoft_identity.py` |
| Tests | `../../../api/tests/unit/test_sync_provider_plugins.py`, `../../../api/tests/integration/test_sync_provider_connection.py`, `test_sync_provider_repository.py`, `../../../api/tests/steps/sync_provider.py` (test-only second provider), `../../../ui/tests/e2e/sync-provider.spec.ts`; file sync: `../../../api/tests/integration/test_file_sync_*.py`, `../../../api/tests/unit/test_file_sync_rules.py`, `test_microsoft_graph_files.py`, `test_test_drive_file_sync.py`, `test_sync_engine_main.py`, `../../../api/tests/steps/file_sync_provider.py` (test-only `file_sync` provider) |

## Change impact

- Changing the callback path, the state, or a provider's scopes affects that provider's app registration (redirect URI, permissions) in every environment.
- Changing the one-open-connection rule needs a migration.
- Changing the provider list's shape affects the Sync UI and `api/developer_docs/operations-v1.json`.
