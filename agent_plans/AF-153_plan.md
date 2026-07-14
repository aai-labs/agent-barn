# AF-153: Gmail OAuth 2.0 "Authenticate with Google" flow

> **Status: implemented and verified** (backend, frontend, deployment wiring, unit tests,
> live UI click-through via `spin-up-local-compose.sh`). Kept here as the design record.
> Setup instructions for the Google Cloud Console side live in
> `Gmail OAuth 2.0 setup (Google Cloud Console).md` at the repo root.

## Context

Previously, when a user assigned a Gmail skill to an agent, the UI asked them to hand-paste
three values into text fields: **Client ID**, **Client secret**, and **Refresh token**
(`ui/src/features/agents/integrations.ts`, the `gmail` provider). The refresh token had to be
minted out-of-band via the manual procedure in
`Gmail, Sheets and Zoho Mail creds generation (for aai-cli).md` — a poor experience that
leaked the OAuth app's client secret to every user.

We wanted a single, app-owned Google OAuth client. Its `google_cloud_client_id` and
`google_cloud_client_secret` live in backend config (never shown to users). When a user adds
the Gmail skill, they see **one "Authenticate with Google" button** instead of the three
fields. Clicking it runs a real OAuth 2.0 authorization-code flow (scope
`https://www.googleapis.com/auth/gmail.readonly`, chosen over full mailbox access or
read+send to keep the initial grant read-only), and the resulting **refresh token** is the
only per-agent secret stored — client id/secret come from config at agent-start time.

Intended outcome: identical downstream behavior (the agent's aai-cli `gmail-work` profile
still works), but credential setup is a one-click Google consent instead of manual token
generation.

---

## Approach

Popup-based authorization-code flow, backend-driven:

1. Button opens a popup (synchronously, to avoid blockers), fetches the Google authorize URL
   from an authenticated backend endpoint, and points the popup at it.
2. Google redirects the popup to a backend callback (proxied through the UI origin so it's
   same-origin with the opener).
3. The callback exchanges the `code` for tokens using the config client id/secret, then serves
   a tiny HTML page that `postMessage`s the **refresh token** back to the opener and closes.
4. The opener stores the refresh token in the existing `IntegrationDraft.content` and submits
   it through the **unchanged** `secrets: [{ provider: "gmail", content: { refreshToken } }]`
   payload on `POST/PATCH /api/v1/agents`.

This reuses the entire existing secret persistence/encryption/agent-start pipeline. The only
new backend surface is two OAuth endpoints; the token exchange reuses the pattern established
by `request_json` in `api/infrastructure/slack/transport.py`.

---

## Backend changes

### 1. Config — `api/core/config.py`
Added two fields to `Config(BaseSettings)` (follows the existing `openrouter_api_key`
pattern):
```python
google_cloud_client_id: str = ""
google_cloud_client_secret: str = ""
```

### 2. New OAuth router — `api/domains/integrations/google_oauth/routes.py`
An `APIRouter(prefix="/integrations")` mounted in `api/api_app.py` alongside the other
routers. Constants: `GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"`,
`GOOGLE_AUTH_ENDPOINT`, `GOOGLE_TOKEN_ENDPOINT`.

- **`GET /integrations/google/authorize-url`** — requires auth (`get_current_user` from
  `api/domains/auth/utils.py`). Builds and returns `{ "authorize_url": ... }` with query
  params: `client_id` (config), `redirect_uri = f"{config.web_app_url}/api/v1/integrations/google/callback"`,
  `response_type=code`, `scope=GMAIL_SCOPE`, `access_type=offline`, `prompt=consent`,
  `include_granted_scopes=true`, and a signed `state`. `state` is a short-TTL JWT
  (`jwt.encode({typ, nonce, exp}, config.secret_signing_key, "HS256")`) — same signing
  key/algorithm the auth domain already uses. Returns 503 if the client id isn't configured.

- **`GET /integrations/google/callback`** — no bearer auth (top-level popup navigation can't
  carry it); instead verifies the signed `state` (rejects on bad signature/expiry/type).
  Exchanges `code` at `GOOGLE_TOKEN_ENDPOINT` via `httpx.post` with form body `client_id`,
  `client_secret` (both from config), `code`, `redirect_uri`, `grant_type=authorization_code`.
  Returns an `HTMLResponse` that runs
  `window.opener.postMessage({ type: "google-oauth", provider: "gmail", refreshToken }, "<web_app_url>")`
  then `window.close()`. On error (Google returns `error`, bad/missing state, non-200
  exchange, or no `refresh_token` in the response), postMessages `{ type: "google-oauth",
  provider: "gmail", error }` instead. `redirect_uri` is byte-identical between the
  authorize-url and the token exchange (Google requires exact match).

### 3. `GmailContent` — `api/domains/agents/models.py`
Made client id/secret optional so an OAuth-created secret can carry only the refresh token,
while legacy blobs (which still hold all three) keep validating:
```python
class GmailContent(SecretContent):
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str
```
No DB migration needed — `agent_secret.content` is an opaque Fernet blob and the provider
CHECK constraint already includes `gmail`.

### 4. Inject config creds at agent start — `api/domains/agents/service.py`
After building the `decrypted` map in `start_agent`, backfill the Gmail entry's client
id/secret **only when empty** (so new OAuth secrets get the shared config client, but legacy
per-agent secrets keep the client their refresh token was issued under — a refresh token is
bound to its issuing client):
```python
gmail = decrypted.get(SecretProvider.GMAIL)
if isinstance(gmail, GmailContent):
    if not gmail.client_id:
        gmail.client_id = self.config.google_cloud_client_id
    if not gmail.client_secret:
        gmail.client_secret = self.config.google_cloud_client_secret
```
`aai_cli_artifacts.py` (`_gmail_block`, `provider_secrets_map`, `build_env`) needed **no
change** — it already reads `client_id`/`client_secret` off the content object.

---

## Frontend changes

### 1. Provider spec — `ui/src/features/agents/integrations.ts`
Added an optional `authMethod?: "google_oauth"` to `IntegrationProvider`. The `gmail` entry
uses it and dropped the three visible fields (the button captures `refreshToken`
programmatically):
```ts
{ id: "gmail", label: "Gmail", authMethod: "google_oauth",
  scopeNote: "Read-only Gmail access via Google sign-in (gmail.readonly). No manual keys needed.",
  fields: [] }
```
Added `isOAuthConnected(draft)` and updated `hasIncompleteIntegration` so an
`authMethod === "google_oauth"` provider counts as complete once `content.refreshToken` is a
non-empty string (its `fields` are empty, so the prior loop would have wrongly passed it).

### 2. New hook — `ui/src/features/agents/hooks/use-google-oauth.ts`
`useGoogleOAuth()` returns `{ connectGoogle, isConnecting }`. `connectGoogle()`:
- Opens a popup synchronously (`window.open("about:blank", ...)`) before any `await`, so
  browsers don't block it.
- Fetches `/api/v1/integrations/google/authorize-url` via the authenticated axios client,
  then sets `popup.location.href` to the returned URL.
- Listens for a same-origin `message` event of `{ type: "google-oauth", ... }`; resolves with
  `refreshToken` on success, rejects with `error` on failure, and rejects if the user closes
  the popup early (poll on `popup.closed`).

### 3. New component — `GoogleAuthButton` in
`ui/src/features/agents/components/hire-dialog-primitives.tsx`
Renders "Authenticate with Google" / "Reconnect Google account" (plus a connected/error
state) with an inline Google "G" glyph, calls the hook, and calls `onConnected(refreshToken)`.

### 4. Wired the button into all four credential render sites
Each site branches on `providerSpec.authMethod === "google_oauth"` to render
`<GoogleAuthButton>` (writing the token via the site's existing
`setField(providerId, "refreshToken", token)`) instead of the field-map loop:
- `SkillsStep` and `IntegrationsStep` — `ui/src/features/agents/components/hire-dialog-steps.tsx`
- `AgentSkillsTab` — `ui/src/features/agents/components/agent-skills-tab.tsx`
- `ConfigDrawer` (repin/Keys tab) — `ui/src/features/agents/components/config-drawer.tsx`

No change to the submission hooks — `useCreateAgent`/`useUpdateAgent` already send
`secrets[]`, and the request interceptor decamelizes `refreshToken → refresh_token`.

---

## Deployment / config wiring

Client secret is sensitive → k8s Secret:
- `helmfile.yaml.gotmpl` — `set:` lines mapping host env `GOOGLE_CLOUD_CLIENT_ID` /
  `GOOGLE_CLOUD_CLIENT_SECRET` onto the `agentfarm-api` release (mirrors `OPENROUTER_API_KEY`).
- `helm/agentfarm-api/values.yaml` — `googleCloudClientId: ""`, `googleCloudClientSecret: ""`.
- `helm/agentfarm-api/templates/secret.yaml` — `GOOGLE_CLOUD_CLIENT_ID` /
  `GOOGLE_CLOUD_CLIENT_SECRET` keys (the deployment already `envFrom`s the whole secret).
- `.env.spec`, `.env.deploy.spec`, `compose.remote.yml`, `compose.yml` — same two vars for
  local dev / compose parity.

---

## One-time Google Cloud Console setup (operational, not code)

Full step-by-step instructions live in
`Gmail OAuth 2.0 setup (Google Cloud Console).md`. Summary:

- One OAuth 2.0 client of type **Web application** (not "Desktop app" — the redirect flow
  requires a registered web redirect URI).
- Authorized redirect URIs: `<WEB_APP_URL>/api/v1/integrations/google/callback` per
  environment.
- Enable the **Gmail API**.
- `gmail.readonly` is a **restricted** scope → Google app verification required before
  non-test users can connect; and while in **Testing** mode, refresh tokens expire after 7
  days (publish the app for long-lived tokens).

---

## Verification performed

- Backend: 33 new unit tests (state sign/verify, authorize-url construction/503 guard,
  callback success/error paths, `GmailContent` optional-field + legacy-blob decryption) +
  full existing suite (371 tests) green. Helm chart renders the new secret keys
  (`helm template` with `--set googleCloudClientId=... --set googleCloudClientSecret=...`).
- Live click-through via `scripts/spin-up-local-compose.sh`: logged in, opened the hire
  wizard, selected the Gmail skill — confirmed the card renders only the "Authenticate with
  Google" button (no manual fields), "Hire" stays disabled until connected, and clicking the
  button round-trips through the real authenticated `/authorize-url` call (surfaced the
  expected `503 Google OAuth is not configured on this server.` since no real Google client
  was configured in the local `.env`).
- Not yet exercised: a full real Google consent grant (requires a live Web-application OAuth
  client + registered redirect URI, which is an operator action, not something this session
  had credentials for).
