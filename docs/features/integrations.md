# Integrations

## Read when

Read before changing tool-provider credential schemas, encryption, Google OAuth, aai-cli or gog configuration, provider-derived Skills, or runtime secret injection. Chat-platform credentials belong to Communication Connections; follow the Communications route in `../INDEX.md` for those changes.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Google Workspace, Zoho Mail, Zoho Calendar, Firecrawl, Slack, Pipedrive, and SharePoint. The per-service Google providers (Gmail, Google Calendar, Google Sheets) are retired; affected agents must reconnect through Google Workspace.

Providers reach their service through one of two CLIs: aai-cli (all of the above except Google Workspace) or gog (Google Workspace only). The two have separate runtime artifacts, secret stores, and agent policy blocks.

## Shared credentials

Shared Credentials are org-scoped, admin-managed credential payloads that any member can attach to an agent. They use the same encryption and provider content models as Agent Secrets.

- Only manual-entry providers are supported for shared credentials (v1): GitHub, Jira, Confluence, Bitbucket, Zoho Mail. OAuth-based providers (Google Workspace, SharePoint) are excluded.
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
- Firecrawl is an infrastructure-level capability: when `AGENT_FIRECRAWL_BASE_URL` and `AGENT_FIRECRAWL_API_KEY` are configured, all agents receive web-fetch/search by default (analogous to LiteLLM). Agents with a per-agent Firecrawl Agent Secret override the platform key.

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

At start, Agent Service decrypts provider payloads, backfills configured Google Workspace client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts the Agent's exact Skill Version pins plus eligible bundled aai-cli Skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

The aai-cli integrations policy is gated on providers that actually have an aai-cli profile. An agent whose only integration is profile-less Google Workspace must not receive instructions claiming that aai-cli profiles are required.

SharePoint uses aai-cli's own `microsoft` profile, so aai-cli needs nothing Agent Barn–specific: `provider = "microsoft"`, `auth_type = "microsoft_delegated"`, the Teams app's `tenant_id` and `client_id`, `scope` = the SharePoint permission plus `offline_access`, and `refresh_token_secret = "microsoft.sharepoint_refresh_token"`. aai-cli refreshes as a public client and writes each rotated refresh token back to its store. The refresh token reaches the pod as `AAI_SECRET_MICROSOFT_SHAREPOINT_REFRESH_TOKEN`, but `aai-cli-setup.sh` writes it only when `AAI_SHAREPOINT_SIGN_IN_ID` differs from the marker beside the store, so a restart keeps the rotated token and a reconnect replaces it; the store therefore lives on a persistent volume (Hermes `/opt/data/.config/aai-cli`, OpenClaw `/home/node/.openclaw/aai-cli`). Microsoft refresh tokens expire after 90 days unused, so an agent that doesn't use SharePoint for that long needs a reconnect. When SharePoint is removed, the boot script (mounted even for agents with no aai-cli profiles) deletes the left-over token and marker from the store. The bundled `aai-microsoft` skill covers more Microsoft 365 services than the sign-in grants; the integrations text tells the agent it has SharePoint only.

Google Workspace materializes through `gog_artifacts.py`: the pod Secret carries the OAuth client and refresh token as `GOG_*` environment, while a ConfigMap-mounted `gog-setup.sh` rebuilds gog state at boot. `GOG_HOME` is on the container filesystem and is wiped and rebuilt on every start; the encrypted Agent Secret remains the source of truth.

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Shared Credential CRUD and lifecycle               | `../../api/domains/shared_credentials/`                                                                                                             |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`                                         |
| gog runtime materialization                        | `../../api/domains/agents/gog_artifacts.py`; gog is pinned in `../../openclaw-base/Dockerfile` and `../../hermes-base/Dockerfile`                 |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/bundled/skills/`, `../../api/domains/skills/skill_seeder.py`                                               |
| Communication platform credentials                 | `../../api/domains/communications/`, [`communications/CHANGELOG.md`](communications/CHANGELOG.md)                                                   |
| Google OAuth (Google Workspace)                    | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| SharePoint sign-in                                 | `../../api/domains/agents/sharepoint_service.py`, `../../api/domains/agents/microsoft_identity.py`, `../../api/domains/integrations/microsoft_oauth/routes.py` |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Tests                                              | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_communication_connections.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A tool Integration provider addition or schema change affects request validation, encrypted compatibility, runtime environment/config generation, built-in Skill seeding, UI forms/Zod schemas, and Agent start tests. Platform additions instead use the shipped Platform Plugin seam. Encryption-key changes require an explicit migration/rotation plan because Agent Secrets, Shared Credentials, and Communication Connection credentials depend on the existing key.
