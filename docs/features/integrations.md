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

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Google Workspace, Firecrawl, Pipedrive, and SharePoint. The per-service Google providers (Gmail, Google Calendar, Google Sheets) are retired; affected agents must reconnect through Google Workspace. Zoho Mail and Zoho Calendar are retired: Zoho Calendar's CalDAV verbs were never carried by any transport we shipped, so it never worked, and Zoho Mail is withdrawn with it. Slack is retired as a tool Integration: the shipped Slack Platform Plugin replaces it and owns that credential, so a Slack credential is always a Communication Connection credential and never an Agent Secret.

Providers reach their service through one of two CLIs: aai-cli (all of the above except Google Workspace) or gog (Google Workspace only). The two have separate runtime artifacts, secret stores, and agent policy blocks. Commands run through either CLI are recorded as Business Actions (see [`business-value.md`](business-value.md)).

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

- Agent Secret payloads are validated against provider-specific schemas before encryption and again after decryption. Agent creation does not trust client-side validation: for providers with a live validator, the service validates the exact submitted manual or shared credential before allocating a LiteLLM key or persisting the Agent. Providers without a live validator remain schema-validated and can be checked through the on-demand validation endpoint.
- An agent has at most one Agent Secret per provider.
- Duplicate providers in create/update payloads are rejected.
- Read APIs return provider and display label, not credential contents.
- Agent updates validate that remaining skill provider requirements are satisfied. Updating a Skill's provider metadata later does not revalidate existing agents.
- Eligible built-in aai-cli skills are mounted at start when their provider credential is configured.
- A built-in skill may declare no required providers when it needs no credential (Excel operates on local `.xlsx` files). Such a skill is never auto-mounted — an empty requirement list is trivially satisfied, so it would otherwise attach to every agent — and is mounted only when explicitly assigned.
- Application deployment secrets, Agent Secrets, Shared Credentials, and Communication Connection credentials are distinct credential classes with different ownership and lifecycles. Connection credentials are owned and validated by shipped Platform Plugins and never become runtime Integration secrets.
- Firecrawl is an infrastructure capability with an operator-default binding and an optional stored override. Their source ownership, independent isolation choices and endpoint rules are defined under [Platform-default Firecrawl](#platform-default-firecrawl).

## Google OAuth

The flow serves Google Workspace, the only Google-backed provider. The authorize and exchange operations require an authenticated user. The caller names the provider and selects services plus read-only access; those choices are carried inside the signed state because Google's callback returns only the code and state. The callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token, the account email, and the granted scopes. Persistence then occurs through the normal Agent Secret create/update flow.

Scopes are derived per request from the selected services and access level rather than being fixed per provider. Stored services, read-only mode, and granted scopes are validated together before encryption. Google Workspace uses the gog CLI and its own credential materialization, separate from aai-cli. A user-supplied Web-application OAuth client is the expected setup; server-owned credentials remain supported where configured.

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

## Runtime materialization

### Optional credential isolation

`agent_integration_isolation` stores desired isolation per Agent, provider and source. A stored Agent Secret owns its `agent_secret` choice even when it references a Shared Credential. The operator's virtual Firecrawl binding owns a separate `platform_default` choice. The Agent owns tenancy. New bindings default OFF; the migration preserves existing isolated GitHub, Jira, Confluence, Bitbucket, Pipedrive, Firecrawl and Google Workspace bindings and direct SharePoint bindings. Replacement, reconnect and shared-source changes preserve the choice. Credential creation and policy initialization share the existing secret/audit transaction; removal deletes only that credential source's policy. Hard Agent deletion cascades both sources.

The Integrations editor exposes provider-specific descriptions and an isolation switch inside each expanded setup. The choice remains a local draft until Apply (or Apply & Restart); Cancel discards it. The read-only list shows configured credentials and their source, without isolation controls or descriptions. OFF sends the required upstream credentials to the runtime. ON uses the provider's proxy or token broker. Reads expose `desired`, `applied`, `generation`, `pending`, `last_verified`, supported modes and descriptions, never credentials. Applied mode is reported only for a ready generation whose binding/source still matches; stopped, failed and pre-upgrade workloads remain unverified. `last_verified` retains the last successful mode for explicit recovery. The catalogue in `api/domains/integrations/capabilities.py` validates available implementations; adding a provider requires both route support and accurate descriptions.

`PUT /organizations/{org}/agents/{agent}/integrations/{provider}/isolation` accepts `{isolated, restart}`. It requires Agent update and secret-manage permissions, accessible Agent scope and the organization's existing write restrictions. Restart additionally requires lifecycle permission. A running change requires `restart=true` and an explicit Apply & Restart confirmation; a stopped change saves pending intent without starting. SharePoint sign-in, updates, removal, start, stop and isolation application use the same lifecycle lock and respect blocking restore operations. User policy changes stage an `agent.updated` audit event with modes/source only.

### Restart and recovery

Application preflights the complete resulting runtime configuration before stopping or saving a different choice. It then terminates the old deployment, waits for its pods to disappear, revokes old gateway authorization, saves intent, and provisions the new generation. `agent_integration_runtime` stores preparing/provisioned/ready/stopping/stopped/failed progress and the last verified binding snapshot, without credential contents. Normal starts also reconcile abandoned deployments before rotating tokens. The application response returns once the replacement deployment is provisioned; image pulls, scheduling, volume attach and setup continue without a readiness deadline that tears down a healthy startup. Agent detail and health reads promote a ready generation or record an actual runtime exit. Retryable image-pull and container-configuration errors retain their deployment and remain unverified; health still reports their diagnostics. A startup exit is established by `CrashLoopBackOff` or a Failed pod with a terminated runtime container, under the lifecycle lock and a fresh generation/observation check. The UI polls an unverified current generation until it is ready or failed. Failed creation or crashed startup terminates the attempted workload, retains desired intent and records a sanitized Agent error. It never silently changes mode. Opening the integration setup and applying it again retries the desired choice; Restore previous mode selects the last verified mode as a draft, then Apply & Restart applies it subject to the same preflight and permission checks. Multi-integration saves stop a running Agent once, save credentials and policy choices, and start only after all saves succeed. A partially failed save leaves it stopped for explicit correction and retry.

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

The existing gateway-routed aai-cli providers use this mode: GitHub, Jira, Confluence, Bitbucket, and Pipedrive. Credential-owned Jira and Confluence upstream URLs are restricted to their provider hosts before forwarding, because `site_url` is user-supplied and becomes the forward target. Isolated bindings are excluded from the aai-cli secret store, so their real credentials are in neither the pod Secret nor `aai-secrets.enc.json`. The plugin's `egress_mode` declares its isolated route; the binding's policy selects direct or isolated materialization without a deployment allowlist.

Credential isolation does not impose an agent egress policy. Hermes and OpenClaw retain unrestricted internet access; the gateway changes where provider credentials live and where authenticated provider requests are executed, not which unrelated destinations an agent may reach.

Isolated Google Workspace materializes through `gog_artifacts.py` as `EgressMode.TOKEN_BROKER` rather than `GATEWAY_PROXY`, because gog exposes no base-URL override but does accept a pre-minted token. The refresh token and OAuth client secret stay in the gateway; the pod receives only its Gateway Token and the mint URL, and there is no keyring, no stored OAuth client and nothing to import. A ConfigMap-mounted `gog-shim.sh` is installed onto `PATH` ahead of `/usr/local/bin` and, on every invocation, exchanges the Gateway Token for a short-lived Google access token which it exports as `GOG_ACCESS_TOKEN` before exec'ing the real binary. Fetching per invocation rather than once at boot matters: a Google access token lasts about an hour and agents run for days, and it makes revocation take effect on the next command rather than the next restart.

Isolated Google Workspace and SharePoint expose expiring upstream credentials to the pod. That is the trade `TOKEN_BROKER` makes — an expiring, non-renewable access token instead of a renewable grant plus a client secret — and it is what allows a CLI that cannot be redirected to be covered at all.

A read-only Google Workspace credential also sets `GOG_READONLY=1`, which makes gog reject mutating API requests locally before dispatch. This is a defence-in-depth backstop layered on the read-only OAuth scopes, not a replacement for them: it is an environment variable, so an agent with a shell can unset it.

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
| Google OAuth (Google Workspace)                    | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| SharePoint sign-in                                 | `../../api/domains/agents/sharepoint_service.py`, `../../api/domains/agents/microsoft_identity.py`, `../../api/domains/integrations/microsoft_oauth/routes.py` |
| SharePoint broker and handoff                      | `../../api/domains/credential_gateway/sharepoint_broker.py`, `../../api/domains/credential_gateway/sharepoint_repository.py`, `../../api/domains/credential_gateway/aai_store.py` |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Isolation and runtime contracts                    | `../../api/tests/integration/test_integration_isolation.py`, `../../api/tests/unit/test_integration_isolation.py`, `../../api/tests/unit/test_integration_runtime.py`, `../../api/runtime_tests/`, `../../ui/tests/e2e/integration-isolation.spec.ts` |
| Tests                                              | `../../api/tests/unit/test_integration_plugins.py`, `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_communication_connections.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A tool Integration provider addition is one Integration Plugin plus its bundled Skill, its content model, and the UI form. A schema change still affects request validation, encrypted compatibility, runtime environment/config generation, built-in Skill seeding, UI forms/Zod schemas, and Agent start tests. A provider reached by a new CLI also needs that CLI's adapter and plugin surface; it does not touch existing providers. Platform additions instead use the shipped Platform Plugin seam. Encryption-key changes require an explicit migration/rotation plan because Agent Secrets, Shared Credentials, and Communication Connection credentials depend on the existing key. Bumping `GOG_VERSION` also requires re-recording the gog command tree the Business Action catalogue is tested against (see [`business-value.md`](business-value.md#change-impact)).
