# Integrations

## Read when

Read before changing provider credential schemas, encryption, Slack app setup, Google OAuth, aai-cli configuration, provider-derived skills, or runtime secret injection.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Gmail, Google Calendar, Google Sheets, Zoho Mail, Zoho Calendar, Firecrawl, Slack, and Pipedrive.

## Shared credentials

Shared Credentials are org-scoped, admin-managed credential payloads that any member can attach to an agent. They use the same encryption and provider content models as Agent Secrets.

- Only manual-entry providers are supported for shared credentials (v1): GitHub, Jira, Confluence, Bitbucket, Zoho Mail. OAuth-based providers (Gmail, Google Calendar, Google Sheets) are excluded.
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

One flow serves every Google-backed provider. The authorize and exchange operations require an authenticated user. The caller names the provider it is connecting; that choice selects the requested scopes and is carried inside the signed state, because the provider callback receives nothing from Google but the code and state. The callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token. Persistence then occurs through the normal Agent Secret create/update flow.

Server-owned Google client credentials are the default. User-supplied client identity is also supported by the route contract. All Google providers request offline access. Gmail requests read-only mail access; Google Sheets requests read/write on spreadsheet values plus metadata-only Drive access, which is what spreadsheet discovery needs.

Each Google provider owns its own secret-store names rather than sharing one entry. The store is a flat namespace, so a user who supplies their own Google client for one provider while using the server-owned client for another would otherwise overwrite one set of credentials with the other.

## Runtime materialization

At start, Agent Service decrypts provider payloads, backfills configured Google client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts provider skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Shared Credential CRUD and lifecycle               | `../../api/domains/shared_credentials/`                                                                                                             |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                         |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/`                                                                                                          |
| Slack configuration token lifecycle                | `../../api/domains/auth/token_service.py`, `../../api/domains/auth/routes.py`                                                                       |
| Google OAuth (Gmail, Google Sheets)                | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Tests                                              | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_slack_config_token.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A provider addition or schema change affects request validation, encrypted compatibility, runtime environment/config generation, built-in skill seeding, UI forms/Zod schemas, and agent start tests. Encryption-key changes require an explicit migration/rotation plan because stored Agent Secrets and Slack configuration tokens depend on the existing key.
