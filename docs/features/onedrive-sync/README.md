# OneDrive sync

## Read when

Read before changing how an Organization connects OneDrive, the platform Microsoft app settings, the `onedrive_sync` domain, or the Microsoft callback for it.

## Role in the system

An Organization Owner or Admin connects OneDrive once from Organization settings. They approve the multi-tenant AAI Labs Microsoft app for their Microsoft tenant, sign in, and pick a SharePoint site. Agent Barn is granted `write` on that one site through `Sites.Selected` and keeps an "Agent Barn" folder in its default document library. This is an Organization resource, not an [Integration](../integrations.md): no Agent is given access to it.

Delivery state and remaining slices are tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Platform app

`ONEDRIVE_SYNC_CLIENT_ID` and `ONEDRIVE_SYNC_CLIENT_SECRET` configure one multi-tenant Microsoft Entra app ([operations](../../guidelines/operations.md)). Its Web redirect URI is `<WEB_APP_URL>/api/v1/integrations/onedrive-sync/callback`. Microsoft accepts plain `http` only for `localhost`. Permissions:

- Application: `Sites.Selected`.
- Delegated: `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`.

When either setting is blank, status reports `available: false` and starting a connection returns 503. The secret is never returned or logged.

## Invariants

- Status (`GET /organizations/{organization_id}/onedrive-sync/connection`) requires `organization.read`, so every Organization Member sees the folder link. Starting a connect or disconnect requires `organization.update`. A caller outside the Organization gets 403, like every Organization-scoped route; 404 concealment applies to Agent resources only.
- Status never includes tokens, the grant id or the tenant. A pending connection whose sign-in has expired reads as not connected.
- An Organization has at most one open (pending or active) connection, enforced by the partial unique index `uq_onedrive_sync_connection_open`. Disconnected rows are kept.
- The tenant is never taken from Microsoft's admin-consent redirect, which an attacker can alter. It comes from the sign-in `id_token`'s `tid`.
- The callback trusts only state this server signed with type `onedrive_sync_state`. A SharePoint or Google state is refused.

## Connect flow

1. The UI opens a popup and calls `GET …/connection/authorize-url?purpose=connect`. It returns 409 while a connection is active.
2. The server signs a state (Organization, user, purpose, encrypted PKCE verifier, public challenge, 10-minute expiry) and returns Microsoft's admin-consent URL at the `organizations` authority with `scope=https://graph.microsoft.com/.default`.
3. Approving the app needs a Microsoft Global Administrator or Privileged Role Administrator. Anyone else gets Microsoft's "Need admin approval" page.
4. Microsoft redirects to `GET /api/v1/integrations/onedrive-sync/callback`. The callback reads `error` first, because Microsoft also sends `admin_consent=True` on a refused consent. A refused or required consent posts "A Microsoft Global Administrator needs to approve Agent Barn for your organization." to the opener.
5. After consent, the callback answers 302 straight to sign-in at the `organizations` authority, with `Sites.FullControl.All`, `Sites.Read.All`, `openid`, `profile`, `prompt=select_account` and the state's PKCE challenge. Microsoft shows no second consent prompt.
6. After sign-in, the callback posts `{type: "onedrive-sync-oauth", code, state}` to the opener.

Completing the sign-in, choosing the site and disconnecting are listed under `Next` in the [change log](CHANGELOG.md).

## Disconnect flow

`GET …/connection/authorize-url?purpose=disconnect` returns 409 unless a connection is active. Otherwise it returns the sign-in URL directly, with no consent step: revoking the site grant needs the administrator's delegated `Sites.FullControl.All`, because an app granted `write` cannot manage site permissions.

## Source map

| Concern | Source |
|---|---|
| Settings | `../../../api/core/config.py` (`is_onedrive_sync_enabled`) |
| Persistence and read contracts | `../../../api/domains/onedrive_sync/models.py`, `repository.py` |
| Flow, state and callback page | `../../../api/domains/onedrive_sync/service.py` |
| Routes | `../../../api/domains/onedrive_sync/routes.py` |
| Folder site for other domains | `../../../api/domains/onedrive_sync/lookup.py` |
| Microsoft identity and Graph calls | `../../../api/domains/agents/microsoft_identity.py`, `microsoft_graph_sites.py` |
| Tests | `../../../api/tests/integration/test_onedrive_sync_connection.py`, `test_onedrive_sync_repository.py` |

## Change impact

Changes to the callback, state or scopes affect the Microsoft app registration (redirect URI, permissions) in every environment. Changes to the open-connection rule need a migration.
