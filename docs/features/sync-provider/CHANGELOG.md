# Sync providers — change log

Status: Active
Epic: AF-383 — Connect an Organization to OneDrive
Related context: [Sync providers](README.md), [ADR](../../adr/2026-10-16-sync-provider-plugin-seam.md), [Integrations](../integrations.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [epic guideline](../../guidelines/epics.md)

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

## Changes

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
