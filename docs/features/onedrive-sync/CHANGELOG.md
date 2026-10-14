# OneDrive sync — change log

Status: Active
Epic: AF-383 — Connect an Organization to OneDrive
Related context: [Integrations](../integrations.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: the platform app settings `ONEDRIVE_SYNC_CLIENT_ID` and `ONEDRIVE_SYNC_CLIENT_SECRET` in `api/core/config.py`. `Config.is_onedrive_sync_enabled` is true only when both are non-blank. Nothing reads the settings yet.
- Delivered: deploy wiring. The API chart Secret renders `ONEDRIVE_SYNC_CLIENT_ID` / `ONEDRIVE_SYNC_CLIENT_SECRET` from `onedriveSyncClientId` / `onedriveSyncClientSecret`; Helmfile reads them from the environment; `deploy.yml` and `deploy-public.yml` pass the shared `vars.ONEDRIVE_SYNC_CLIENT_ID` and `secrets.ONEDRIVE_SYNC_CLIENT_SECRET`. Unset values render blank, leaving OneDrive sync unavailable.
- Delivered: verification of the Microsoft flow (T-1, T-5) against a real tenant, recorded in the 2026-10-14 entry.
- Delivered: `MicrosoftIdentityClient.exchange_code(..., client_secret=None)` redeems as a confidential client when a secret is given (still with the PKCE verifier), and `build_app_permission_consent_url(..., state=None)` carries a `state`. Existing SharePoint callers pass neither and are unchanged.
- In transition: nothing. No GitHub variable or secret is set yet, so every deployed environment renders the settings blank.
- Next: Microsoft Graph site search, site lookup by id, and folder creation.
- Blockers: none. Enabling an environment later needs the GitHub variable and secret, and that environment's `<WEB_APP_URL>/api/v1/integrations/onedrive-sync/callback` registered on the Microsoft app.

Acceptance criteria amendment: another Organization's caller gets **403**, not 404. `get_current_user()` refuses a caller outside the path Organization before any route runs, as for every Organization-scoped resource; 404 concealment applies to Agent resources only ([RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md)).

## Changes

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
