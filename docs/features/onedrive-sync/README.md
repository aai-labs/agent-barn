# OneDrive sync

## Read when

Read before changing how an Organization connects OneDrive, the platform Microsoft app settings, the `sync_provider` domain or its OneDrive plugin, or the provider callback.

OneDrive is the first provider of the generic sync provider seam (`api/domains/sync_provider/`). The generic service owns permissions, the signed state, the callback page, the connection lifecycle and one connection at a time. The OneDrive plugin (`plugins/onedrive.py`) owns everything Microsoft: sign-in, site search, the grant, the folder and its rollback.

## Role in the system

An Organization Owner or Admin connects OneDrive once from Organization settings. They approve the multi-tenant AAI Labs Microsoft app for their Microsoft tenant, sign in, and pick a SharePoint site. Agent Barn is granted `write` on that one site through `Sites.Selected` and keeps an "Agent Barn" folder in its default document library. This is an Organization resource, not an [Integration](../integrations.md): no Agent is given access to it.

Delivery state and remaining slices are tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Platform app

`ONEDRIVE_SYNC_CLIENT_ID` and `ONEDRIVE_SYNC_CLIENT_SECRET` configure one multi-tenant Microsoft Entra app ([operations](../../guidelines/operations.md)). Its Web redirect URI is `<WEB_APP_URL>/api/v1/integrations/sync-provider/onedrive/callback`. Microsoft accepts plain `http` only for `localhost`. Permissions:

- Application: `Sites.Selected`.
- Delegated: `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`.

When either setting is blank, OneDrive is left out of the provider list and its routes return 404 "OneDrive isn't available on this server." The secret is never returned or logged.

## Invariants

- The provider list (`GET /organizations/{organization_id}/sync-providers`) requires `organization.read`, so every Organization Member sees the folder link. It has one entry per provider offered on this server: the descriptor (`key`, `display_name`, `tagline`, `folder_hint`, `connect_hint`, `location_noun`, `schema_version`, `capabilities`), `approval_url`, `connection` (status, location name and URL, folder link, connected time, or `null`), `can_connect` and `blocked_reason`. Every route under `…/sync-providers/{provider_key}/connection` requires `organization.update`, and an unknown or unoffered provider is 404. A caller outside the Organization gets 403, like every Organization-scoped route; 404 concealment applies to Agent resources only.
- The list never includes tokens, the account (tenant) or provider data such as the grant id. A pending connection whose sign-in has expired reads as not connected.
- Connections are stored in `sync_provider_connection`, keyed by `provider_key`. Disconnected rows are kept.
- The tenant is never taken from Microsoft's admin-consent redirect, which an attacker can alter, and the callback never echoes it. It comes from the sign-in `id_token`'s `tid`, stored as the connection's `account_id`.
- The callback trusts only state this server signed with type `sync_provider_state` for that provider. A SharePoint or Google state, or another provider's, is refused.

## One connection at a time

An Organization has at most one open (pending or active) connection across all providers. Two places enforce it:

- `SyncProviderService._blocking_connection`. While another provider is connected, starting or completing a connect returns 409 "Disconnect OneDrive first." While another provider is pending, the message is "Finish connecting OneDrive, or start over, first." The list reports the same text as `blocked_reason`, with `can_connect: false`. Another provider's expired sign-in doesn't block, and is cleared when a new sign-in completes.
- The partial unique index `uq_sync_provider_connection_open` on `organization_id`.

The UI holds no rule of its own; it renders `can_connect` and `blocked_reason`.

**Changing to several providers at once:** remove `_blocking_connection` and its use, add a migration that replaces the index with one on `(organization_id, provider_key)`, and rewrite the "one connection at a time" groups in `test_sync_provider_connection.py` and `test_sync_provider_repository.py`. Routes, the list shape, repository queries and the UI stay as they are.

## Connect flow

Paths below are relative to `/organizations/{organization_id}/sync-providers/onedrive`.

**Approving the app (once per Microsoft organization).** A Microsoft Global Administrator or Privileged Role Administrator approves the app. The OneDrive entry carries `approval_url`: Microsoft's admin-consent link at the `organizations` authority with `scope=https://graph.microsoft.com/.default` and no state. The settings section gives it to Owners and Admins to forward. After approving, Microsoft redirects to the callback with `admin_consent=True`, which shows "Agent Barn is approved for your organization. The person connecting can now connect OneDrive." Once approved, connecting needs no Global Administrator.

1. The UI opens a popup and calls `GET …/connection/authorize-url?purpose=connect`. It returns 409 while OneDrive is active or another provider blocks it.
2. The server signs a state (Organization, user, provider, purpose, encrypted PKCE verifier, 10-minute expiry) and returns Microsoft's sign-in URL at the `organizations` authority, with `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`, `prompt=select_account` and the PKCE challenge. There is no consent step, and no consent prompt in an approved organization.
3. Microsoft redirects to `GET /api/v1/integrations/sync-provider/onedrive/callback`. The callback reads `error` first. Where the app isn't approved yet, Microsoft reports it (`consent_required`, or AADSTS65001/65004/90094/90095), and the callback posts "A Microsoft Global Administrator needs to approve Agent Barn for your organization." to the opener.
4. After sign-in, the callback posts `{type: "sync-provider-oauth", code, state}` to the opener.
5. The opener calls `POST …/connection/sign-in {code, state}` (`organization.update`; a read-only API key is refused like on any mutating route). The server:
   1. requires a connect state issued to this caller for this Organization and provider (400 otherwise);
   2. redeems the code at the `organizations` authority as a confidential client (the platform secret plus the PKCE verifier);
   3. takes the tenant from the `id_token`'s `tid` (400 if missing);
   4. requires both `Sites.FullControl.All` and `Sites.Read.All` in the granted scope (400 otherwise).

   It then stores a pending connection holding the delegated access token Fernet-encrypted (`AGENT_TOKEN_ENCRYPTION_KEY`) until the token expires. No refresh token is requested. A new sign-in replaces an existing pending connection; one is refused (409) while a connection is active. Microsoft refusals are 400 and an unreachable Microsoft is 502.

6. The picker calls `GET …/connection/locations?search=<term>` (`organization.update`), which runs Graph's site search with the administrator's delegated token. The term is required: Microsoft doesn't document what an empty search returns.
7. The opener calls `POST …/connection/location {location_id}` with the site id (`organization.update`). The server:
   1. reads the site from Graph (400 if unknown), so the stored name and URL never come from the client;
   2. refuses (409, "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick another site.") when any Agent in the Organization, including a deleted one, has a recorded SharePoint selected-sites grant on that site id (compared case-insensitively). Deleting an Agent neither revokes nor forgets its grants, so they still count. Nothing is granted when refused;
   3. grants the platform app `write` on that site, with display name "Agent Barn", using the administrator's delegated token. Microsoft requires the signer to be a SharePoint Administrator and a member of the site, so a refusal is a 403 that says so;
   4. gets an app-only token in the connection's tenant;
   5. ensures the "Agent Barn" folder at the root of the site's default document library;
   6. activates the connection with the site, the folder link and the grant id (in `provider_data`), and drops the delegated token.

   If anything fails after the grant, the grant is revoked with the delegated token and the connection stays pending (502). Throttling is 503.

Searching or choosing without a fresh pending connection is 409: the administrator connects again.

`DELETE …/connection` (`organization.update`) abandons a pending connection and leaves an active one alone.

## Disconnect flow

1. `GET …/connection/authorize-url?purpose=disconnect` returns 409 unless a connection is active. Otherwise it returns the sign-in URL directly, with no consent step. Revoking the site grant needs the administrator's delegated `Sites.FullControl.All`, because an app granted `write` cannot manage site permissions.
2. After sign-in the opener calls `POST …/connection/disconnect {code, state}` (`organization.update`). The server:
   1. requires a disconnect state issued to this caller for this Organization and provider (400);
   2. requires an active connection (409);
   3. redeems the code exactly as for connecting;
   4. requires the sign-in's `tid` to equal the connection's tenant, compared case-insensitively (400);
   5. revokes the stored grant on the site;
   6. marks the connection disconnected.

   A refused revoke is 403 (SharePoint Administrator and site member), throttling 503, an unreachable Microsoft 502. In all three cases the connection stays active.
3. The "Agent Barn" folder and its files are left in place. The Organization may connect again.

## Organization settings

Settings → **Sync** (`?tab=sync`) is visible to every Organization Member. It reads the provider list and shows one row per offered provider (`ui/src/features/sync-provider/`). The UI has no provider-specific branches: every text it shows about a provider comes from the provider's entry.

- No provider offered on this server: "No sync providers are available on this server."
- Each row has a letter tile, the provider's name, and a subtitle: its `tagline`, "Connecting…" while pending, or "● Connected to {location}" in green when active.
- Not connected:
  - Owners and Admins get **Connect**. It opens the provider's sign-in popup and then posts the code to the sign-in route. Connect is enabled only when `can_connect` is true; otherwise the row shows `blocked_reason`, for example "Disconnect OneDrive first.". Otherwise the row shows the provider's `connect_hint`; for OneDrive that is who must approve and who may connect. When the provider has `approval_url`, the row offers it as the **approval link** to forward. A provider error from the callback, such as the Global Administrator message, is shown inline.
  - Members are told an Owner or Admin can connect.
- Pending:
  - Owners and Admins of a provider with `location_picker` get the picker inline: a search that needs a term (labelled from `location_noun`, "Search SharePoint sites"), a result list, and **Use**. The API's `detail` is shown inline when choosing fails, for example a site an Agent already holds. Reloading the page resumes at the picker while the sign-in is fresh. **Start over** abandons the unfinished connection.
  - Members are told no {location_noun} has been chosen yet.
- Active: **Open** (labelled "Open in OneDrive") links to the folder in a new tab, with the provider's `folder_hint` underneath ("Add shortcut to My files" for OneDrive). Owners and Admins also get **Disconnect**, confirmed in a dialog that says the folder and its files stay where they are. It then opens the sign-in popup and posts the code to the disconnect route. A refusal, such as a signer who isn't a SharePoint Administrator and site member, is shown inline and the connection stays.
- Connecting or disconnecting one provider refetches the list, because it changes whether the others may connect.

The query is keyed by Organization id, so switching Organization never shows the previous one's providers.

## Keeping Agents out of the folder site

- Connecting refuses a site any Agent in the Organization, including a deleted one, holds a recorded SharePoint selected-sites grant on (see the connect flow).
- The SharePoint integration refuses to grant an Agent the site holding the Organization's folder (409, before any grant), through `SyncProviderLookupService.folder_location_id(organization_id, "onedrive")`. See [SharePoint selected sites](../integrations.md#sharepoint-selected-sites).
- Delegated-mode SharePoint Agents have no per-site grant: they reach whatever the person who signed them in can open, which may include the folder site. This gap is accepted and documented, not enforced.

## Known limits

- **Delegated-mode SharePoint Agents** can reach the folder site through their signer's own access; only selected-sites grants are guarded.
- **Deleting an Organization** deletes its connection row (cascade) but leaves the platform app's grant on the site in Microsoft. Nobody is signed in to revoke it. An administrator can remove it from the site's permissions.
- **There is no lock between an Agent's selected-sites grant and an Organization connecting at the same moment.** Each check reads the other's state independently, so two requests finishing together can both pass.
- **Approving the app needs a Microsoft Global Administrator or Privileged Role Administrator**, once per Microsoft organization, and again only if the app's permissions change. Connecting and disconnecting need a SharePoint Administrator who is a member of the site.
- **The app shows as "unverified" on Microsoft's consent page** until the AAI Labs app has publisher verification.

## Source map

| Concern | Source |
|---|---|
| Settings | `../../../api/core/config.py` (`is_onedrive_sync_enabled`) |
| Plugin seam and registry | `../../../api/domains/sync_provider/plugins/base.py`, `registry.py`, `providers.py`; registered in `../../../api/infrastructure/app.py` |
| OneDrive plugin | `../../../api/domains/sync_provider/plugins/onedrive.py` |
| Persistence and read contracts | `../../../api/domains/sync_provider/models.py`, `repository.py` |
| Flow, state, callback page, one at a time | `../../../api/domains/sync_provider/service.py` |
| Routes | `../../../api/domains/sync_provider/routes.py` |
| Folder site for other domains | `../../../api/domains/sync_provider/lookup.py`, used by `../../../api/domains/agents/sharepoint_service.py` |
| Microsoft identity and Graph calls | `../../../api/domains/agents/microsoft_identity.py`, `microsoft_graph_sites.py` |
| UI | `../../../ui/src/features/sync-provider/`, registered as `sync` in `../../../ui/src/features/organizations/components/organization-settings-utils.ts` and `../../../ui/src/app/dashboard/[orgId]/settings/page.tsx` |
| Tests | `../../../api/tests/unit/test_sync_provider_plugins.py`, `../../../api/tests/integration/test_sync_provider_connection.py`, `test_sync_provider_repository.py`, `../../../ui/tests/e2e/sync-provider.spec.ts` |

## Change impact

Changes to the callback path, state or scopes affect the Microsoft app registration (redirect URI, permissions) in every environment. Changes to the open-connection rule need a migration.
