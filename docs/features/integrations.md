# Integrations

## Read when

Read before changing provider credential schemas, encryption, Slack app setup, Google OAuth, aai-cli configuration, provider-derived skills, or runtime secret injection.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Google Workspace, Zoho Mail, Zoho Calendar, Firecrawl, Slack, and Pipedrive. The per-service Google providers (Gmail, Google Calendar, Google Sheets) are retired: their enum members, content models, credential rows, and seeded skills were deleted by migration. Affected agents must reconnect through Google Workspace, and the retired providers are absent from the UI.

Providers reach their service through one of two CLIs: aai-cli (all of the above except Google Workspace) or the gog CLI (Google Workspace only). The two share nothing — no profiles, no secret store — and each has its own runtime artifacts and its own agent policy block.

## Shared credentials

Shared Credentials are org-scoped, admin-managed credential payloads that any member can attach to an agent. They use the same encryption and provider content models as Agent Secrets.

- Only manual-entry providers are supported for shared credentials (v1): GitHub, Jira, Confluence, Bitbucket, Zoho Mail. OAuth-based providers (Google Workspace) are excluded.
- An agent gets either a shared credential or a per-agent secret for a given provider, not both.
- Any org member can list and attach shared credentials; only admins (owner/admin roles) can create, update, or delete them.
- Multiple shared credentials per provider per org are allowed (e.g. "Production GitHub" and "Staging GitHub").
- Deletion is blocked while any non-deleted agent references the shared credential (RESTRICT FK).
- Shared credential names are unique within an organization.
- When an agent starts, the runtime resolves shared credential content by following the `agent_secret.shared_credential_id` FK to decrypt from the shared credential row.

## Invariants

- Agent Secret payloads are validated against provider-specific schemas before encryption and again after decryption.
- An agent has at most one Agent Secret per provider.
- Duplicate providers in create/update payloads are rejected.
- Read APIs return provider and display label, not credential contents.
- Agent updates validate that remaining skill provider requirements are satisfied. Updating a Skill's provider metadata later does not revalidate existing agents.
- Eligible built-in aai-cli skills are mounted at start when their provider credential is configured.
- A built-in skill may declare no required providers when it needs no credential (Excel operates on local `.xlsx` files). Such a skill is never auto-mounted — an empty requirement list is trivially satisfied, so it would otherwise attach to every agent — and is mounted only when explicitly assigned.
- Application deployment secrets, per-user Slack configuration tokens, per-agent Agent Secrets, and Shared Credentials are distinct credential classes with different ownership and lifecycles.
- Firecrawl is an infrastructure-level capability: when `AGENT_FIRECRAWL_BASE_URL` and `AGENT_FIRECRAWL_API_KEY` are configured, all agents receive web-fetch/search by default (analogous to LiteLLM). Agents with a per-agent Firecrawl Agent Secret override the platform key.

## Slack setup

Per-user Slack configuration tokens support automated Slack app creation. They are encrypted at rest, exposed only as masked previews, validated when saved, and rotated through their refresh token when used. Agent Slack bot/app tokens are separate per-agent credentials.

## Google OAuth

The flow serves Google Workspace, the only Google-backed provider. The authorize and exchange operations require an authenticated user. The caller names the provider it is connecting, which is carried inside the signed state because the callback receives nothing from Google but the code and state; a state naming a retired provider no longer resolves. The callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token. Persistence then occurs through the normal Agent Secret create/update flow.

Scopes are derived per request from the caller's service selection and read-only choice rather than being fixed per provider, so `/authorize-url` accepts `services` and `read_only`, and rejects any provider other than Google Workspace rather than serving scopes no integration can use. The scope sets mirror the pinned gog release's own derivation, because the services recorded in the credential are re-declared to gog at agent start. Stored `services` and `read_only` must remain covered by the recorded consent scopes; this is validated before the credential is encrypted. And because gog keys stored tokens by account email, the flow always requests the identity scopes and `/token` returns the `email` claim decoded from the id_token — unverified, since the token arrives directly from Google's token endpoint in our own server-to-server exchange. `/token` also returns `granted_scopes`; the consent screen lets a user withhold individual scopes, so what was granted can be narrower than what was requested, and the credential records the granted set.

A user-supplied Web-application OAuth client is the expected setup for Google Workspace rather than an option. Google caps any app requesting unverified sensitive or restricted scopes at 100 grant-users for the lifetime of the project, and that cap cannot be reset — so a server-owned client only suits a verified deployment or a Workspace-internal app. Consent-screen publishing status matters too: apps left in Testing get refresh tokens that expire after 7 days, which is what the validator's `invalid_grant` message points at.

## Runtime materialization

At start, Agent Service decrypts provider payloads, backfills configured Google client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts provider skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

The aai-cli integrations policy block is gated on providers that actually have a profile, not on any secret being present: an agent whose only integrations are profile-less would otherwise be told that aai-cli is the only way to reach them and that `--profile` is mandatory, above an empty list.

Google Workspace materializes through its own builders (`gog_artifacts.py`): the pod Secret carries the OAuth client and refresh token as `GOG_*` environment, and a ConfigMap-mounted `gog-setup.sh` — secret-free, entirely env-driven — installs the client and imports the token at boot. `GOG_HOME` is on the container filesystem, deliberately not the PVC, and is wiped and rebuilt on every start: the encrypted credential row is the single source of truth, the keyring password is regenerated per start, and removing the credential removes pod access at the next restart with nothing left behind. Note that `start_agent` also computes an `aai_home` that *is* the Hermes PVC (`/opt/data`); the two are different concepts and must not be unified. The integration ships no skill file, so the AGENTS.md block built by `build_gog_policy_md` is the only place an agent learns gog exists.

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Shared Credential CRUD and lifecycle               | `../../api/domains/shared_credentials/`                                                                                                             |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                         |
| gog runtime materialization (Google Workspace)     | `../../api/domains/agents/gog_artifacts.py`; `gog` binary pinned in `../../openclaw-base/Dockerfile` and `../../hermes-base/Dockerfile`             |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/`                                                                                                          |
| Slack configuration token lifecycle                | `../../api/domains/auth/token_service.py`, `../../api/domains/auth/routes.py`                                                                       |
| Google OAuth (Google Workspace)                    | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Tests                                              | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_slack_config_token.py`, `../../api/tests/unit/test_google_oauth.py`, `../../api/tests/unit/test_gog_artifacts.py` |

## Change impact

A provider addition or schema change affects request validation, encrypted compatibility, runtime environment/config generation, built-in skill seeding, UI forms/Zod schemas, and agent start tests. Encryption-key changes require an explicit migration/rotation plan because stored Agent Secrets and Slack configuration tokens depend on the existing key.
