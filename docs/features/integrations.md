# Integrations

## Read when

Read before changing tool-provider credential schemas, encryption, Google OAuth, aai-cli or gog configuration, provider-derived Skills, or runtime secret injection. Chat-platform credentials belong to Communication Connections; follow the Communications route in `../INDEX.md` for those changes.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Provider extension seam

Per-provider behavior lives on an Integration Plugin in `../../api/domains/integrations/plugins/`: one class per provider carrying its credential model, live validator, Shared Credential eligibility, bundled skill binding, egress mode, and — for aai-cli providers — its `--profile` slug, config.toml block, secret-store entries, and agents_md lines. A provider is reached by exactly one runtime tool (`aai-cli`, `gog`, or none), and that tool's adapter owns file layout, ordering, and shared prose rather than branching per provider.

The registry validates plugin coherence at import, so a malformed or half-added provider fails process startup rather than one Agent's start. `SHARED_CREDENTIAL_ALLOWED_PROVIDERS`, the aai-cli profile slugs, the secret-store map, and each bundled skill's required providers are all derived from the plugins. `PROVIDER_DISPLAY_NAMES`, `PROVIDER_CONTENT_MODELS`, and `PROVIDER_VALIDATORS` remain where they are to avoid an import cycle, and `../../api/tests/unit/test_integration_plugins.py` pins them against the plugins so they cannot drift.

Plugins are trusted release artifacts, not dynamically installed packages: adding a provider is a merged PR, never runtime registration.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Google Workspace, Gmail, Gmail with an app password, Firecrawl, Pipedrive, SharePoint, and Apollo. Gmail is a read-only integration beside Google Workspace: one sign-in on the shared Google client, Gmail only, reached through aai-cli's `email` commands. Gmail with an app password is a separate read-only provider for accounts that connect with a Google app password instead; see [Gmail app password](#gmail-app-password). The per-service Google Calendar and Google Sheets providers are retired; affected agents must reconnect through Google Workspace. Zoho Mail and Zoho Calendar are retired: Zoho Calendar's CalDAV verbs were never carried by any transport we shipped, so it never worked, and Zoho Mail is withdrawn with it. Slack is retired as a tool Integration: the shipped Slack Platform Plugin replaces it and owns that credential, so a Slack credential is always a Communication Connection credential and never an Agent Secret.

Providers reach their service through one of two CLIs: aai-cli (all of the above except Google Workspace, including both Gmail providers) or gog (Google Workspace only). For Gmail with an app password, aai-cli only carries the request: the credential gateway reads the inbox itself. The two have separate runtime artifacts, secret stores, and agent policy blocks. Commands run through either CLI are recorded as Business Actions (see [`business-value.md`](business-value.md)).

## Shared credentials

Shared Credentials are org-scoped, admin-managed credential payloads that any member can attach to an agent. They use the same encryption and provider content models as Agent Secrets.

- Only manual-entry providers are supported for shared credentials (v1): GitHub, Jira, Confluence, Bitbucket. OAuth-based providers (Google Workspace, SharePoint) are excluded.
- An agent gets either a shared credential or a per-agent secret for a given provider, not both.
- Any org member can list and attach shared credentials; only admins (owner/admin roles) can create, update, or delete them.
- Multiple shared credentials per provider per org are allowed (e.g. "Production GitHub" and "Staging GitHub").
- Deletion is blocked while any non-deleted agent references the shared credential (RESTRICT FK).
- Shared credential names are unique within an organization.
- When an agent starts, the runtime resolves shared credential content by following the `agent_secret.shared_credential_id` FK to decrypt from the shared credential row.

## Invariants

- Agent Secret payloads are validated against provider-specific schemas before encryption and again after decryption. Agent creation does not trust client-side validation: for providers with a live validator, the service validates the exact submitted manual or shared credential before allocating a LiteLLM key or persisting the Agent. Providers without a live validator remain schema-validated and can be checked through the on-demand validation endpoint. Apollo's validator proves only that the key is valid: Apollo offers no check of which endpoints a key may call, so an agent can still get 403 from endpoints the key or the Apollo plan does not cover.
- An agent has at most one Agent Secret per provider.
- Duplicate providers in create/update payloads are rejected.
- Read APIs return provider and display label, not credential contents.
- Agent updates validate that remaining skill provider requirements are satisfied. Updating a Skill's provider metadata later does not revalidate existing agents.
- Eligible built-in aai-cli skills are mounted at start when their provider credential is configured.
- A built-in skill may declare no required providers when it needs no credential (Excel operates on local `.xlsx` files). Such a skill is never auto-mounted — an empty requirement list is trivially satisfied, so it would otherwise attach to every agent — and is mounted only when explicitly assigned.
- Application deployment secrets, Agent Secrets, Shared Credentials, and Communication Connection credentials are distinct credential classes with different ownership and lifecycles. Connection credentials are owned and validated by shipped Platform Plugins and never become runtime Integration secrets.
- Firecrawl is an infrastructure capability with an operator-default binding and an optional stored override. Their source ownership, independent isolation choices and endpoint rules are defined under [Platform-default Firecrawl](#platform-default-firecrawl).

## Google OAuth

The flow serves the two Google-backed providers, Google Workspace and Gmail. The authorize and exchange operations require an authenticated user. The caller names the provider; for Google Workspace it also selects services plus read-only access; those choices are carried inside the signed state because Google's callback returns only the code and state. The callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token, the account email, and the granted scopes. Persistence then occurs through the normal Agent Secret create/update flow.

The server-owned client (`GOOGLE_CLOUD_CLIENT_ID`/`SECRET`) also serves "Sign in with Google" for Agent Barn accounts, which asks only for identity and keeps no Google token; see [Identity and Organizations](identity-and-organizations.md#google-sign-in-and-self-signup). Both callbacks must be registered on that client.

For Google Workspace, scopes are derived per request from the selected services and access level; stored services, read-only mode, and granted scopes are validated together before encryption. Google Workspace uses the gog CLI and its own credential materialization, separate from aai-cli. Gmail always asks for read-only Gmail plus identity and ignores any service or access-level choice; the stored grant must include read-only Gmail. Gmail is materialized as an aai-cli `gmail-work` profile. A user-supplied Web-application OAuth client is the expected setup; server-owned credentials remain supported where configured.

The web app does not offer Gmail sign-in yet: it signs in on the shared Google app, which Google has not verified, so users would see Google's unverified-app warning and the app's cap on how many people can sign in. Gmail with an app password is offered instead. The provider keeps `offered: false` in `../../ui/src/features/agents/integrations.ts`, which keeps it, and any skill that needs it, out of every add list; an Agent that already has a Gmail sign-in still shows it and can remove it. The API, the sign-in flow and its tests (skipped in `agent-configuration-page.spec.ts`) are unchanged, ready for when the app is verified.

## Gmail app password

A Google app password unlocks a whole mailbox over IMAP (reading, deleting, and sending through SMTP) and cannot be scoped, so this provider is gateway-served only (`EgressMode.GATEWAY_SERVED`). It has no direct mode: new bindings default to isolated, the isolation endpoint refuses direct, and the UI shows the switch locked on. The content is the address and app password; the spaces Google displays in the password are dropped on validation, and there is no host field, so the password can only ever reach `imap.gmail.com`. Creating an Agent signs in once to reject a wrong or revoked password, like every provider's live validator.

The agent reaches it with aai-cli, like the other aai-cli integrations, through an isolated Custom API profile (`gmail-inbox`, `provider = "custom_api"`) that holds no credential: `base_url = "https://gmail.internal/v1"`, `gateway_url = {gateway}/served/request`, and `gateway_token_env = AF_GATEWAY_TOKEN_GMAIL_APP_PASSWORD`. aai-cli posts the complete request object (`method`, `url`, `query`, `body`, `headers`) to that gateway route with only the gateway token and never contacts the `base_url` host, which is a label. The pod receives only `AF_GATEWAY_URL`, its gateway token, and that profile. `AGENTS.md` gives the two exact commands, `custom-api request --method GET --url https://gmail.internal/v1/messages` (optional `--query q=<Gmail search>` and `--query limit=<1-50>`) and `.../messages/<id>`, and never shows `curl` or a token variable: Hermes refuses a whole `AGENTS.md` that does ("exfil_curl"), which would drop every other platform instruction with it. The Hermes runtime contract runs the image's own scanner over the generated block.

`POST /gateway/v1/served/request` is generic, and separate from `/custom-api/request`, which belongs to Custom API connections and their own credentials: it resolves the gateway token, refuses any provider whose plugin is not `GATEWAY_SERVED`, decrypts the credential, calls the plugin's `serve` hook, audits a `served` lifecycle event, and returns `{status, body}`. Everything Gmail-specific lives in `GmailAppPasswordPlugin.serve`, which accepts only `GET .../messages` (newest first, at most 50) and `GET .../messages/{id}` (headers, readable text, attachment names) and refuses any other method (405 `read_only`), address (404), query or body (400) before Gmail is contacted. It reads through `GmailInbox` (`../../api/infrastructure/google/gmail_imap.py`), which enforces read-only rather than relying on Google: the inbox is opened with EXAMINE, messages are fetched with `BODY.PEEK` so reading leaves them unread, and no command that changes mail is ever issued. It signs in only after verifying Gmail's TLS certificate and hostname (imaplib's default context checks neither), so a server posing as Gmail never sees the app password. A search is sent as a UTF-8 IMAP literal (`CHARSET UTF-8`), so any language works, and control characters are refused, so it cannot add commands. Every call is bounded because the gateway serves every Organization: a listing fetches only the newest messages by position (no `SEARCH ALL`, which imaplib refuses past a 1 MB line), a search covers the newest 50,000 inbox messages, and a message larger than 2 MB is read only from its start and marked `truncated`. A part in a charset Python does not know is decoded with replacement characters rather than failing. Token problems get the gateway's usual opaque 403. Gmail failures come back as the upstream status inside a successful envelope (`502 mail_sign_in_failed`, `502 upstream_unreachable`, `400 invalid_query`, `404 not_found`), because aai-cli shows the agent nothing from a gateway error status.

This needs aai-cli's Custom API gateway mode (aai-labs/aai-cli#30), so it requires `hermes-base` 0.2.9 and `openclaw-base` 0.7.6 or later. The gateway now opens outbound IMAPS connections to `imap.gmail.com:993`; any future egress restriction on the gateway must allow it.

## SharePoint sign-in

SharePoint signs in with Microsoft (delegated `Sites.ReadWrite.All` or `Sites.Read.All`, plus `offline_access`) on the agent's **Microsoft Teams connection app**, so it is only offered to agents with a Teams connection. The sign-in is a **public client**: the code is redeemed with a PKCE verifier and never with the app's secret, which `CommunicationsService.get_teams_app_identity` does not even return (app id and tenant only). No app owned by the platform and no publisher verification are involved.

One-time setup on the Teams app, walked through in the UI with direct Entra links:

1. Redirect URI `{web_app_url}/api/v1/integrations/microsoft/callback` under **Mobile and desktop applications** (not Web). Under Web, Microsoft demands the secret and refuses the redemption with AADSTS7000218.
2. **Allow public client flows: Yes.**
3. API permissions → Microsoft Graph → Delegated → `Sites.ReadWrite.All` / `Sites.Read.All`.
4. Where the organization restricts user consent (common since Microsoft's 2025 default for Files/Sites permissions), an administrator grants admin consent, on the API permissions page or through the approval link the UI offers (`/v2.0/adminconsent`, returning to the same callback).

Flow:

- `GET /organizations/{org}/agents/{agent}/integrations/sharepoint/setup?connection_id` returns the app id, tenant, redirect URI and the approval links (both access levels).
- `GET …/authorize-url?connection_id&read_only` (agent update + secret manage) signs a state carrying agent, connection, access level, the user who started it and the PKCE verifier (Fernet-encrypted, since the state passes through Microsoft and the browser). The authority is the Teams app's tenant.
- The unauthenticated callback posts `{code, state}` (or `{adminConsent: true}`) to the opener and maps Microsoft's errors to fixes: consent errors (`consent_required`, AADSTS65001/90094/90095) to "an administrator needs to approve"; a declined consent reads as cancelled.
- `POST …/sign-in` re-checks state, user and permissions, redeems the code without a secret, requires the id_token `tid` to match the Teams app's tenant (GUIDs compared case-insensitively; a tenant given as a domain is trusted to the tenant-specific authority, and the stored credential always keeps Microsoft's `tid`), the SharePoint permission and a refresh token, and stores the `sharepoint` Agent Secret (connection, tenant, client id, account, granted permissions, access level, refresh token, a new `sign_in_id`) with its audit event. It returns only the email and access level. AADSTS7000218 maps to "check Mobile and desktop applications and public client flows". The generic secret upsert rejects `sharepoint` content (`SIGN_IN_ONLY_PROVIDERS`).

## SharePoint selected sites

The second mode, one per agent (`SharePointContent.mode`; stored credentials without it read as `delegated`, while the UI offers selected sites first and preselects it for an agent without SharePoint): the agent reaches only sites an administrator granted to the agent's Teams app under the **application** permission `Sites.Selected`, independent of any person's access. Microsoft only supports `Sites.Selected` app-only, and app-only tokens are minted with the Teams app's secret, so the API mints them and the pod never sees that secret.

Extra setup on the Teams app: API permissions → Microsoft Graph → **Application** → `Sites.Selected`, admin-consented (`app_permission_consent_url` from `/setup`, a `/v2.0/adminconsent` link for `.default`). The redirect URI and public client flows are still needed for the administrator's sign-in.

Flow:

- `GET …/authorize-url?connection_id&read_only&mode=selected_sites&sites=…` reduces each site URL to its root (`sharepoint_sites.normalize_site_url`, mirrored by the UI's `normalizeSiteUrl`), puts the complete desired list in the signed state, and asks for delegated `Sites.FullControl.All` plus identity scopes, **without `offline_access`**, so Microsoft returns no refresh token.
- `POST …/sign-in` checks the tenant and that `Sites.FullControl.All` was granted, then reconciles with the administrator's access token, which is used only in that request and never stored: every new site is looked up first, new sites are granted `read`/`write` (`POST /sites/{id}/permissions` for the Teams app), kept sites are left alone unless the access level changed (then their grant's roles are updated in place, `PATCH /sites/{id}/permissions/{perm}`), grants recorded for a different Teams app are all replaced, and removed sites are revoked (`DELETE /sites/{id}/permissions/{perm}`; already gone counts as done). A failed grant or level change takes back the attempt's grants and puts changed levels back; errors name the site's address, never Graph's path; a grant that couldn't be revoked stays on record (502) so the next sign-in retries. Graph refusing to manage permissions (a non-administrator) is a 403. Graph rejecting a change (400/409) is a 502 naming the site; throttling (429) is a 503 that says to wait; both still undo the attempt. Finishing a sign-in holds a per-agent advisory lock (`AgentRepository.sharepoint_sign_in_lock`, non-blocking like `lifecycle_lock`) through the save, so a second sign-in finishing meanwhile gets a 409 instead of overwriting the first's result. The credential stores each site's URL, site id and permission id, the administrator's account, and no token.
- `GET /organizations/{org}/agents/{agent}/integrations/sharepoint` returns the mode, account, access level and site URLs (never permission ids) so the UI can show and edit the list.
- `POST /ingest/v1/agents/{agent}/integrations/sharepoint/token`, authenticated by the agent's ingest key, returns `{access_token, expires_at}`: a client-credentials token from `CommunicationsService.get_teams_app_credentials` (server-side only; the secret is excluded from `repr`), cached per Teams app (keyed by a hash of the secret) until five minutes before it lapses. 404 not connected, 409 for a delegated agent, a disabled Teams connection, or Microsoft refusing the app; 502 Microsoft unreachable. It spares aai-cli a Microsoft credential but is not a security boundary: native Teams gives the pod the same secret (`MSTEAMS_APP_PASSWORD` / `TEAMS_CLIENT_SECRET`) for the bot, and a token minted with it reaches the same sites and carries the same application permissions.

The site holding the Organization's [OneDrive sync](sync-provider/README.md#onedrive-provider) folder is never granted to an Agent: once the new sites are resolved and before any grant, a sign-in naming that site (by Graph site id, case-insensitively) is refused with 409 "This site holds the Organization's OneDrive folder, so Agents can't be given SharePoint access to it." and nothing changes. The reverse holds too: OneDrive sync refuses a site any Agent in the Organization holds a recorded grant on. Delegated mode has no per-site grant, so a delegated agent reaches whatever its signer can, including the folder site.

Grants live on the sites, not in any token: every app-only token for the Teams app reaches every site granted to it. So the credential is never dropped while it holds grants, or a later setup on the same app (the same agent after a removal, or another agent the app moves to) would inherit sites nobody chose. While a selected-sites credential exists, the API refuses with 409: removing SharePoint in an agent update, starting or completing a delegated sign-in, removing the agent's Teams connection, and pointing that connection at another app (a rotated secret on the same app is fine). The way out is the removal sign-in, `authorize-url?mode=selected_sites&remove_all=true`: the same administrator sign-in, which revokes every recorded grant and deletes the credential (`POST …/sign-in` returns `null`); grants that couldn't be revoked stay on record (502) for the next try. Retiring the agent is allowed, with a warning in the UI that its sites stay granted. Grants attach to the agent's own Teams app, so site scope is per agent. Two setup cautions follow from the pod holding the app's secret and the app allowing public client flows: the app should carry no application permission beyond `Sites.Selected` (every one of them reaches the pod), and the tenant should block the device code flow for it with Conditional Access, since a device code sign-in by a tricked administrator would hand the agent a delegated `Sites.FullControl.All` token. Rotate the app's secret if an agent may have leaked it. Graph's workbook API has no app-only support, so Excel workbook commands are unavailable in this mode; files still download and upload. The pinned CLI permits brokered delegated workbook calls, so Microsoft Graph remains the authorization boundary for app-only tokens.

## Runtime materialization

### Optional credential isolation

`agent_integration_isolation` stores desired isolation per Agent, provider and source. A stored Agent Secret owns its `agent_secret` choice even when it references a Shared Credential. The operator's virtual Firecrawl binding owns a separate `platform_default` choice. The Agent owns tenancy. New bindings default OFF; the migration preserves existing isolated GitHub, Jira, Confluence, Bitbucket, Pipedrive, Firecrawl and Google Workspace bindings and direct SharePoint bindings. Replacement, reconnect and shared-source changes preserve the choice. Credential creation and policy initialization share the existing secret/audit transaction; removal deletes only that credential source's policy. Hard Agent deletion cascades both sources.

The Integrations editor exposes provider-specific descriptions and an isolation switch inside each expanded setup. The choice remains a local draft until Apply (or Apply & Restart); Cancel discards it. The read-only list shows configured credentials and their source, without isolation controls or descriptions. OFF sends the required upstream credentials to the runtime. ON uses the provider's proxy or token broker. Reads expose `desired`, `applied`, `generation`, `pending`, `last_verified`, supported modes and descriptions, never credentials. Applied mode is reported only for a ready generation whose binding/source still matches; stopped, failed and pre-upgrade workloads remain unverified. `last_verified` retains the last successful mode for explicit recovery. The catalogue in `api/domains/integrations/capabilities.py` validates available implementations; adding a provider requires both route support and accurate descriptions.

`PUT /organizations/{org}/agents/{agent}/integrations/{provider}/isolation` accepts `{isolated, restart}`. It requires Agent update and secret-manage permissions, accessible Agent scope and the organization's existing write restrictions. Restart additionally requires lifecycle permission. A running change requires `restart=true` and an explicit Apply & Restart confirmation; a stopped change saves pending intent without starting. SharePoint sign-in, updates, removal, start, stop and isolation application use the same lifecycle lock and respect blocking restore operations. User policy changes stage an `agent.updated` audit event with modes/source only.

### Restart and recovery

Application preflights the complete resulting runtime configuration before stopping or saving a different choice. It then terminates the old deployment, waits for its pods to disappear, revokes old gateway authorization, saves intent, and provisions the new generation. `agent_integration_runtime` stores preparing/provisioned/ready/stopping/stopped/failed progress and the last verified binding snapshot, without credential contents. Normal starts also reconcile abandoned deployments before rotating tokens. The application response returns once the replacement deployment is provisioned; image pulls, scheduling, volume attach and setup continue without a readiness deadline that tears down a healthy startup. Both runtimes report readiness 503 until plugin and credential setup complete; each container boot clears its setup marker before starting the health server. Agent detail and health reads promote a ready generation or record an actual runtime exit, including exits after a generation was verified ready. A ready generation in CrashLoopBackOff is failed only after at least two restarts, allowing Kubernetes to recover from a transient exit. Retryable image-pull and container-configuration errors retain their deployment and remain unverified; health still reports their diagnostics. A startup exit is established by `CrashLoopBackOff` or a Failed pod with a terminated runtime container, under the lifecycle lock and a fresh generation/observation check. The UI polls an unverified current generation until it is ready or failed. Failed creation or crashed startup terminates the attempted workload, retains desired intent and records a sanitized Agent error. It never silently changes mode. Opening the integration setup and applying it again retries the desired choice; Restore previous mode selects the last verified mode as a draft, then Apply & Restart applies it subject to the same preflight and permission checks. Multi-integration saves stop a running Agent once, save credentials and policy choices, and start only after all saves succeed. A partially failed save leaves it stopped for explicit correction and retry.

Pod readiness establishes successful credential setup; isolated SharePoint additionally requires its durable authentication handoff flag. Neither a stored boolean nor a running status alone establishes applied mode. Existing pods are not restarted by migration or application rollout. Their binding policies preserve legacy routing and their source-bound legacy gateway tokens remain valid until explicit stop/restart. A new token is bound to its Agent, Organization, provider, credential binding/source and generation. Authorization uses the generation's mode, so pending intent cannot withdraw a running generation's access. Removal, replacement of the binding, stale generation, stop or failure reject the token.

### Credential adapters

`api/domains/integrations/runtime.py` materializes explicit bindings through aai-cli, gog and Firecrawl adapters. Duplicate bindings, mismatched content models, unsupported routes and missing gateway authorization fail without direct fallback. Mixed modes independently select profiles and environment. Direct aai-cli receives real credentials in Secret environment and its encrypted store; isolated bindings get gateway profiles/tokens. Setup removes only known entries selected for isolation, after any required handoff. A scoped Jira/Confluence direct credential missing `cloud_id` fails rather than omitting its profile.

Direct Google imports its OAuth client and refresh token into a disposable encrypted gog keyring with a fresh password. Only Secret environment carries credentials. Setup removes an older broker wrapper and rebuilds the fixed state directory. Isolated Google uses the per-invocation broker and receives only expiring access tokens. Both modes retain the read-only guard. The real offline import contracts run in both runtime images.

Startup retains Firecrawl's Hermes web/browser overlay and TTL, the OpenClaw plugin overlay, and `tools_md` integration context. The runtime fingerprint now includes activated adapters. Native Slack, Telegram, Discord and Teams credentials remain governed by their Platform contract and are unaffected by these choices.

### SharePoint broker and handoff

Direct SharePoint retains delegated public-client refresh in the persistent aai-cli store. Isolated SharePoint uses a `microsoft` / `token_url` profile pointing to `POST /gateway/v1/token` with its dedicated gateway-token environment variable. Typed Graph files, lists and Excel commands receive temporary Graph access tokens and call Graph directly; no upload/download buffering proxy is introduced. The runtime profile contains no Microsoft refresh token, tenant/client settings or renewable secret-store references. The pinned aai-cli compatibility patch permits delegated Excel through this profile and prevents falling back to unrelated API-token environment variables when its dedicated token is missing.

The broker serializes each refresh using PostgreSQL runtime/credential row locks, reloads the encrypted grant after locking, and caches access tokens in encrypted credential content across gateway replicas. It refreshes when less than five minutes remain and atomically stores any rotated refresh token with the access-token cache. Rotation emits no user secret-updated event. Reconnect replaces the sign-in and cache; `invalid_grant` requires reconnect, while provider/network failures return a sanitized authentication error without fallback.

For direct → isolated, the old pod is terminated first. Before the new Agent process starts, setup submits its old encrypted store, key and sign-in marker to the generation-scoped `/sharepoint/handoff` endpoint. A matching marker imports the latest PVC grant; a marker from an older sign-in uses the newer DB reconnect. The broker proves the selected grant with a live refresh and commits rotation plus the handoff flag before allowing setup to remove the PVC token and marker. Invalid stores or unknown revisions fail closed and preserve the PVC for reconnect/retry. Completed imports are idempotent across container restarts; later payloads cannot replace the proven grant. Store/key material is neither persisted nor logged by the gateway. PyNaCl/libsodium reads the pinned CLI's version-1 XChaCha20-Poly1305 format.

For isolated → direct, termination precedes reading the latest rotated DB grant under the same locks. A fresh `store_revision` changes the pod marker so setup imports that grant. Microsoft's previously issued refresh tokens are not revoked by a mode switch; changing storage cannot retract credentials an Agent already received. Native Teams app credentials remain separate. A sign-in unused long enough to expire requires reconnect in either mode.

### Platform-default Firecrawl

When the operator configures both Firecrawl URL and key, an Agent without a stored Firecrawl credential gets a virtual Platform Firecrawl row in Keys. Its separate choice defaults OFF and survives attachment/removal of a stored override. ON sends a source-bound gateway token and URL to the runtime; the operator key remains service-side. The gateway uses the configured operator URL, supplied to both API and gateway deployments. A default token cannot resolve against an attached stored credential, and a stored token cannot resolve against the default source. Operator endpoints are validated during preflight. Stored isolated Firecrawl remains pinned to the managed provider URL; stored direct mode may use its configured URL.

### Runtime artifacts

At start, Agent Service decrypts provider payloads, backfills configured Google Workspace client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts the Agent's exact Skill Version pins plus eligible bundled aai-cli Skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

The aai-cli integrations policy is gated on providers that actually have an aai-cli profile. An agent whose only integration is profile-less Google Workspace must not receive instructions claiming that aai-cli profiles are required.

Direct SharePoint uses aai-cli's own `microsoft` profile, so aai-cli needs nothing Agent Barn–specific: `provider = "microsoft"`, `auth_type = "microsoft_delegated"`, the Teams app's `tenant_id` and `client_id`, `scope` = the SharePoint permission plus `offline_access`, and `refresh_token_secret = "microsoft.sharepoint_refresh_token"`. aai-cli refreshes as a public client and writes each rotated refresh token back to its store. The refresh token reaches the pod as `AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN`, but `aai-cli-setup.sh` writes it only when `AAI_SHAREPOINT_SIGN_IN_ID` differs from the marker beside the store, so a restart keeps the rotated token and a reconnect replaces it; the direct store therefore lives on a persistent volume (Hermes `/opt/data/.config/aai-cli`, OpenClaw `/home/node/.openclaw/aai-cli`), excluded from restore points on both runtimes (`HERMES_EXCLUDED`/`OPENCLAW_EXCLUDED`). Microsoft refresh tokens expire after 90 days unused, so an agent that doesn't use SharePoint for that long needs a reconnect. When SharePoint is removed, the boot script (mounted even for agents with no aai-cli profiles) deletes the left-over token and marker from the store. The bundled `aai-microsoft` skill covers more Microsoft 365 services than the sign-in grants; the integrations text tells the agent it has SharePoint only.

An isolated provider whose Integration Plugin declares `EgressMode.GATEWAY_PROXY` routes through the credential gateway. Direct mode follows the [optional isolation contract](#optional-credential-isolation). Ordinary HTTP profiles keep aai-cli's existing `auth_type = "bearer_token"`, point their existing `base_url` or `site_url` override at `/p/<provider>`, and use the existing `token_env` field to load `AF_GATEWAY_TOKEN_<PROVIDER>`. The gateway also accepts the Gateway Token as a Basic-auth password, so a transport that cannot send a bearer header is still able to authenticate the pod-to-gateway hop. The token authenticates only the pod-to-gateway hop; the gateway replaces it with the provider's real authorization before forwarding. No aai-cli gateway-specific behavior is required.

Redirects retain provider credential headers only within the same origin (scheme, host and effective port). Changing the port or downgrading HTTPS to HTTP strips credentials, and a later redirect back does not restore them.

The existing gateway-routed aai-cli providers use this mode: GitHub, Jira, Confluence, Bitbucket, Pipedrive, and Apollo. Credential-owned Jira and Confluence upstream URLs are restricted to their provider hosts before forwarding, because `site_url` is user-supplied and becomes the forward target. Isolated bindings are excluded from the aai-cli secret store, so their real credentials are in neither the pod Secret nor `aai-secrets.enc.json`. The plugin's `egress_mode` declares its isolated route; the binding's policy selects direct or isolated materialization without a deployment allowlist.

Credential isolation does not impose an agent egress policy. Hermes and OpenClaw retain unrestricted internet access; the gateway changes where provider credentials live and where authenticated provider requests are executed, not which unrelated destinations an agent may reach.

Apollo uses the same proxy route as Pipedrive. Direct mode uses `apollo_api_key` and the `apollo.api_token` store entry. Isolated mode uses a gateway bearer profile rooted at `/p/apollo/api/v1`; the gateway forwards only to `https://api.apollo.io` and injects `x-api-key` as a sensitive header. The pinned CLI patch routes `apollo health` through the same profile while retaining Apollo's distinct `/v1/auth/health` path; typed and passthrough commands retain `/api/v1`. Existing Apollo credentials are backfilled to direct mode without replacing saved policy choices. Both runtime images must include `aai-apollo-routing.patch` before enabling isolated Apollo. Endpoint scope and plan restrictions still apply and can produce 403 responses.

Isolated Google Workspace materializes through `gog_artifacts.py` as `EgressMode.TOKEN_BROKER` rather than `GATEWAY_PROXY`, because gog exposes no base-URL override but does accept a pre-minted token. The refresh token and OAuth client secret stay in the gateway; the pod receives only its Gateway Token and the mint URL, and there is no keyring, no stored OAuth client and nothing to import. A ConfigMap-mounted `gog-shim.sh` is installed onto `PATH` ahead of `/usr/local/bin` and, on every invocation, exchanges the Gateway Token for a short-lived Google access token which it exports as `GOG_ACCESS_TOKEN` before exec'ing the real binary. Hermes explicitly sources the runtime tool PATH after its usual user shell initialization files, so its login-shell terminal snapshot retains the wrapper. Local `gog auth list` and `gog auth credentials list` can be empty in isolated mode; service commands, rather than stored credentials, verify brokered access. Fetching per invocation rather than once at boot matters: a Google access token lasts about an hour and agents run for days, and it makes revocation take effect on the next command rather than the next restart.

Isolated Google Workspace and SharePoint expose expiring upstream credentials to the pod. That is the trade `TOKEN_BROKER` makes — an expiring, non-renewable access token instead of a renewable grant plus a client secret — and it is what allows a CLI that cannot be redirected to be covered at all.

A read-only Google Workspace credential also sets `GOG_READONLY=1`, which makes gog reject mutating API requests locally before dispatch. This is a defence-in-depth backstop layered on the read-only OAuth scopes, not a replacement for them: it is an environment variable, so an agent with a shell can unset it.

In direct selected-sites mode the profile is aai-cli's generic `auth_type = "token_url"`: `token_url = {ingest_base_url}/agents/{id}/integrations/sharepoint/token` and `api_token_secret = "agentfarm.ingest_key"`. `aai-cli-setup.sh` stores `$INGEST_API_KEY` under that name on every boot (the ingest key is regenerated per start), and no SharePoint token or sign-in marker reaches the pod; a refresh token left from an earlier delegated sign-in is removed. The tool context lists the granted sites. Isolated selected-sites mode instead uses the credential gateway URL and dedicated generation token; its handoff proves the existing app-only token service before removing any old delegated PVC entry, and imports no delegated grant. Both routes reuse the same Teams-app token issuer. The direct ingest token route remains available to isolated selected-sites Agents through their ingest key. Native Teams still supplies its app secret to the runtime, so this isolation choice cannot isolate that Communication Connection credential or reduce the app's site grants. Both runtimes take the same profile and script. `token_url` arrived in aai-cli with aai-labs/aai-cli#27, so selected sites needs `openclaw-base` 0.7.5 and `hermes-base` 0.2.8 or later (0.7.4 and 0.2.7 were published before #27 merged); current images pin a revision from aai-cli `main` that includes #27, under the [runtime versioning rules](../guidelines/operations.md#versioning-and-releases).

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Per-provider behavior (Integration Plugins)        | `../../api/domains/integrations/plugins/`                                                                                                           |
| Shared Credential CRUD and lifecycle               | `../../api/domains/shared_credentials/`                                                                                                             |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`                                         |
| gog runtime materialization                        | `../../api/domains/agents/gog_artifacts.py`; gog is pinned in `../../openclaw-base/Dockerfile` and `../../hermes-base/Dockerfile`                 |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/bundled/skills/`, `../../api/domains/skills/skill_seeder.py`                                               |
| Communication platform credentials                 | `../../api/domains/communications/`, [`communications/CHANGELOG.md`](communications/CHANGELOG.md)                                                   |
| Gmail app password                                 | `GmailAppPasswordPlugin` in `../../api/domains/integrations/plugins/providers.py`, `../../api/infrastructure/google/gmail_imap.py`, `serve_custom_api_request` in `../../api/domains/credential_gateway/routes.py` |
| Google OAuth (Google Workspace)                    | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| SharePoint sign-in                                 | `../../api/domains/agents/sharepoint_service.py`, `../../api/domains/agents/microsoft_identity.py`, `../../api/domains/integrations/microsoft_oauth/routes.py` |
| SharePoint broker and handoff                      | `../../api/domains/credential_gateway/sharepoint_broker.py`, `../../api/domains/credential_gateway/sharepoint_repository.py`, `../../api/domains/credential_gateway/aai_store.py` |

| SharePoint selected sites                          | `../../api/domains/agents/microsoft_graph_sites.py`, `../../api/domains/agents/sharepoint_sites.py`, `../../api/domains/ingest/routes.py` |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Isolation and runtime contracts                    | `../../api/tests/integration/test_integration_isolation.py`, `../../api/tests/unit/test_integration_isolation.py`, `../../api/tests/unit/test_integration_runtime.py`, `../../api/runtime_tests/`, `../../api/k8s_runtime_tests/` ([on-demand usage](../guidelines/testing.md#on-demand-integration-isolation-verification)), `../../ui/tests/e2e/integration-isolation.spec.ts` |
| Tests                                              | `../../api/tests/unit/test_integration_plugins.py`, `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_communication_connections.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A tool Integration provider addition is one Integration Plugin plus its bundled Skill, its content model, and the UI form. A schema change still affects request validation, encrypted compatibility, runtime environment/config generation, built-in Skill seeding, UI forms/Zod schemas, and Agent start tests. A provider reached by a new CLI also needs that CLI's adapter and plugin surface; it does not touch existing providers. Platform additions instead use the shipped Platform Plugin seam. Encryption-key changes require an explicit migration/rotation plan because Agent Secrets, Shared Credentials, and Communication Connection credentials depend on the existing key. Bumping `GOG_VERSION` also requires re-recording the gog command tree the Business Action catalogue is tested against (see [`business-value.md`](business-value.md#change-impact)).

## Custom API connections

Custom API connections configure arbitrary public HTTPS APIs without adding a
provider-specific CLI or generating tools from OpenAPI. An Agent may have multiple
connections. Each has an immutable, Agent-scoped identifier (`inventory`, for
example), a display name, and a base URL that defines its allowed origin and path.
Creation derives the identifier from the name by lowercasing it and replacing
spaces and other unsupported characters with hyphens (up to 64 characters).
Identifiers are not editable and remain unchanged when the display name changes;
names producing an existing identifier are rejected. Custom API setup is part of
the existing Integrations editor, with the same Add, Apply and Cancel workflow.
API-specific instructions belong in the assigned Template or Skills.

Connections live in `api/domains/custom_api/`, independently of the one-Secret-per-
provider registry. Each row encrypts its authentication and additional headers with
the existing Agent credential encryption key. Supported authentication is none,
Bearer token, a named API-key header (including a complete custom Authorization
scheme), or Basic username/password. Additional headers may be ordinary or secret;
secret values, auth tokens, and Basic credentials are never returned by read APIs.
Header entries are lists so the web client's case transformations do not rename
HTTP header names.

`/organizations/{organization_id}/agents/{agent_id}/custom-api-connections` lists
and creates connections; `/{connection_id}` updates or deletes one. Visibility uses
the accessible-Agent repository query. Writes require `agent.update` and
`agent.secret.manage`, the Agent lifecycle lock, and no managed update or blocking
restore. Ordinary writes require a stopped Agent. Identifiers cannot be changed.
Updates preserve omitted auth/header fields. An auth object must explicitly name
its type; omitted secret values retain their saved value only for the same auth
type. A submitted headers list replaces the list; an omitted value retains a saved
secret only for the same header name. Changing authentication type requires the new
credential fields. Removing a header from the list removes it. CRUD stages an Agent
Updated Domain Event atomically without credential values.

Isolation is optional, defaults **off**, and is selected independently for each
connection. Direct mode injects that connection's real credentials into the pod's
Kubernetes Secret environment. Isolation keeps those credentials outside the pod
and injects a per-connection, per-start gateway token instead. Direct mode does not
prevent the Agent from reading its credentials. Startup transfers these values over
stdin into aai-cli's encrypted store on the Agent volume. Generated profiles contain
secret references; the ConfigMap contains no authentication tokens, passwords or
header values. A namespaced manifest removes the previous Custom API entries before
installing current values, including after isolation, auth/header changes and
connection deletion. Built-in integration entries are preserved. Old managed
Kubernetes Secrets are replaced on start.

Startup installs an aai-cli configuration containing only encrypted-store paths
even when no CLI integrations remain. This clears stale profiles while the setup
script removes former Custom API entries and any removed SharePoint sign-in.

`POST /{connection_id}/apply` accepts the update fields plus `restart`. Applying to
a running Agent requires `restart: true` and `agent.lifecycle.manage`. The server
prepares the complete resulting runtime configuration before stopping the old pod,
persists the intended change, and starts a new generation. Failure leaves the saved
intent available for retry. Start, restart, managed update and recovery use the same
materializer. The integration runtime snapshot records connection identity, scope,
mode and a credential revision hash; only a ready generation counts as applied, and
the existing last verified snapshot remains available during recovery. Removing a
connection, stopping the Agent, or replacing its generation invalidates its token.

The editor submits multiple Custom API changes to `POST /custom-api-connections/apply`
with `creates`, `updates` (`id` plus `data`), `deletes` (connection IDs), and an
outer `restart` choice. The server checks all targets, resulting identifiers,
credentials, and runtime artifacts under the Agent lifecycle lock before stopping
the Agent, then persists the connection changes and their events in one transaction.
Invalid batches leave the running Agent and saved connections unchanged. A running
Agent requires explicit restart authorization and is restarted once for the batch;
a stopped Agent stays stopped unless `restart` is requested.
For edits combining Custom API and built-in provider changes, the editor first
uses `POST /custom-api-connections/preflight` with the same batch body. This validates
the resulting Custom API configuration without saving or stopping, before entering
the shared provider stop/save/start workflow. The batch is revalidated when saved;
this preflight does not reserve configuration across requests or make built-in
provider and Custom API writes atomic together. Failed mixed saves retain the
restart choice for retry within the editor.

Both Hermes and OpenClaw use the generic Custom API command in aai-cli. Profiles
use `custom-api-<connection_identifier>` to avoid collisions with built-in providers.
This requires a runtime image whose aai-cli includes the `custom-api` command:
`openclaw-base` 0.7.6 or `hermes-base` 0.2.9 or later. The shared command is:

```sh
aai-cli --profile custom-api-inventory custom-api request --request-json - <<'JSON'
{"method":"GET","url":"https://api.example.com/v1/items","query":{"limit":10}}
JSON
```

The command takes an absolute URL only; it never joins a relative path to the base
URL. It supports GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS, query objects,
JSON or text bodies, and additional request headers. Configured headers cannot be
overridden. Responses contain the HTTP `status` and a JSON or text `body`, with
known literal credential values redacted. Upstream responses are untrusted and
redaction cannot guarantee removal of encoded or transformed secrets. Request and response bodies are limited to 1 MiB
and upstream connections time out after 30 seconds. The isolated interface posts the
same request to `/gateway/v1/custom-api/request`; that endpoint derives its Agent
and connection solely from the hashed, generation-bound token.

The destination policy allows public HTTPS on the configured port (443 by default).
Requests must match the configured effective port. Internal/private/link-local,
loopback, multicast and reserved addresses are unsupported in this initial version.
All DNS answers must be public and the connection is pinned to a validated address
while TLS verifies the configured hostname. Environment proxies are not used.
The destination must match the configured origin and path segment boundary.
Userinfo, fragments, backslashes, dot segments, duplicate slashes, encoded separators,
and double encoding are refused; ordinary encoded resource names are supported.
Redirects are refused in both modes, including same-origin redirects. The configured
base URL is a destination scope, not an endpoint prefix to join automatically.
