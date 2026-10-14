# OneDrive sync — change log

Status: Active
Epic: AF-383 — Connect an Organization to OneDrive
Related context: [Integrations](../integrations.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: the platform app settings `ONEDRIVE_SYNC_CLIENT_ID` and `ONEDRIVE_SYNC_CLIENT_SECRET` in `api/core/config.py`. `Config.is_onedrive_sync_enabled` is true only when both are non-blank. Nothing reads the settings yet.
- Delivered: deploy wiring. The API chart Secret renders `ONEDRIVE_SYNC_CLIENT_ID` / `ONEDRIVE_SYNC_CLIENT_SECRET` from `onedriveSyncClientId` / `onedriveSyncClientSecret`; Helmfile reads them from the environment; `deploy.yml` and `deploy-public.yml` pass the shared `vars.ONEDRIVE_SYNC_CLIENT_ID` and `secrets.ONEDRIVE_SYNC_CLIENT_SECRET`. Unset values render blank, leaving OneDrive sync unavailable.
- Delivered: verification of the Microsoft flow (T-1, T-5) against a real tenant, recorded in the 2026-10-14 entry.
- Delivered: `MicrosoftIdentityClient.exchange_code(..., client_secret=None)` redeems as a confidential client when a secret is given (still with the PKCE verifier), and `build_app_permission_consent_url(..., state=None)` carries a `state`. Existing SharePoint callers pass neither and are unchanged.
- Delivered: `MicrosoftGraphSites.search_sites`, `get_site` (both return `SiteSummary(id, name, web_url)`, the name preferring `displayName`) and `ensure_folder` (returns `FolderRef(item_id, web_url)`). `ensure_folder` reads the folder by path at the root of the site's default library, creates it on 404 with `conflictBehavior: fail`, and reuses one created in between.
- Delivered: the `onedrive_sync_connection` table (migration `734b0f2b3793`) with statuses `pending`, `active` and `disconnected`. The partial unique index `uq_onedrive_sync_connection_open` allows one open (non-disconnected) row per Organization; rows cascade on Organization delete.
- Delivered: `OneDriveSyncRepository` in `api/domains/onedrive_sync/`:
  - `create_pending` replaces a pending row in the same transaction and raises `OneDriveSyncConnectionConflict` while one is active;
  - `activate` (pending only) records the site, folder and grant id and clears the delegated token;
  - `mark_disconnected` (active only), `delete_pending` and `get_open`.
- Delivered: `OneDriveSyncLookupService.folder_site_id(organization_id)`, the active connection's site id or None, for other domains.
- Delivered: `GET /organizations/{organization_id}/onedrive-sync/connection` (status, `organization.read`), `GET …/connection/authorize-url?purpose=connect|disconnect` (`organization.update`), and the unauthenticated `GET /api/v1/integrations/onedrive-sync/callback`. The behaviour contract is [`README.md`](README.md).
- Delivered: `POST …/connection/sign-in` redeems the administrator's code into a pending connection holding their encrypted delegated token, and `DELETE …/connection` abandons a pending connection.
- Delivered: `GET …/connection/sites?search=` and `POST …/connection/site`. Choosing a site grants the platform app `write` on it, ensures the "Agent Barn" folder as the app, and activates the connection; a failure after the grant revokes it.
- Delivered: choosing a site is refused (409, one line) when any Agent in the Organization, including a deleted one, has a recorded SharePoint selected-sites grant on it.
- In transition: nothing. No GitHub variable or secret is set yet, so every deployed environment renders the settings blank.
- Next: disconnect (the administrator signs in again to revoke the grant).
- Blockers: none. Enabling an environment later needs the GitHub variable and secret, and that environment's `<WEB_APP_URL>/api/v1/integrations/onedrive-sync/callback` registered on the Microsoft app.

Acceptance criteria amendment: another Organization's caller gets **403**, not 404. `get_current_user()` refuses a caller outside the path Organization before any route runs, as for every Organization-scoped resource; 404 concealment applies to Agent resources only ([RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md)).

## Changes

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
