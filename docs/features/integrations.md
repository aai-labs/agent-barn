# Integrations

## Read when

Read before changing tool-provider credential schemas, encryption, Google OAuth, aai-cli or gog configuration, provider-derived Skills, or runtime secret injection. Chat-platform credentials belong to Communication Connections; follow the Communications route in `../INDEX.md` for those changes.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Google Workspace, Zoho Mail, Zoho Calendar, Firecrawl, Slack, and Pipedrive. The per-service Google providers (Gmail, Google Calendar, Google Sheets) are retired; affected agents must reconnect through Google Workspace.

Providers reach their service through one of two CLIs: aai-cli (all of the above except Google Workspace) or gog (Google Workspace only). The two have separate runtime artifacts, secret stores, and agent policy blocks.

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
- Application deployment secrets, Agent Secrets, Shared Credentials, and Communication Connection credentials are distinct credential classes with different ownership and lifecycles. Connection credentials are owned and validated by shipped Platform Plugins and never become runtime Integration secrets.
- Firecrawl is an infrastructure-level capability: when `AGENT_FIRECRAWL_BASE_URL` and `AGENT_FIRECRAWL_API_KEY` are configured, all agents receive web-fetch/search by default (analogous to LiteLLM). Agents with a per-agent Firecrawl Agent Secret override the platform key.

## Google OAuth

The flow serves Google Workspace, the only Google-backed provider. The authorize and exchange operations require an authenticated user. The caller names the provider and selects services plus read-only access; those choices are carried inside the signed state because Google's callback returns only the code and state. The callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token, the account email, and the granted scopes. Persistence then occurs through the normal Agent Secret create/update flow.

Scopes are derived per request from the selected services and access level rather than being fixed per provider. Stored services, read-only mode, and granted scopes are validated together before encryption. Google Workspace uses the gog CLI and its own credential materialization, separate from aai-cli. A user-supplied Web-application OAuth client is the expected setup; server-owned credentials remain supported where configured.

## Runtime materialization

At start, Agent Service decrypts provider payloads, backfills configured Google Workspace client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts provider skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

The aai-cli integrations policy is gated on providers that actually have an aai-cli profile. An agent whose only integration is profile-less Google Workspace must not receive instructions claiming that aai-cli profiles are required.

Google Workspace materializes through `gog_artifacts.py`: the pod Secret carries the OAuth client and refresh token as `GOG_*` environment, while a ConfigMap-mounted `gog-setup.sh` rebuilds gog state at boot. `GOG_HOME` is on the container filesystem and is wiped and rebuilt on every start; the encrypted Agent Secret remains the source of truth.

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Shared Credential CRUD and lifecycle               | `../../api/domains/shared_credentials/`                                                                                                             |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                         |
| gog runtime materialization                       | `../../api/domains/agents/gog_artifacts.py`; gog is pinned in `../../openclaw-base/Dockerfile` and `../../hermes-base/Dockerfile`               |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/`                                                                                                          |
| Communication platform credentials                 | `../../api/domains/communications/`, [`communications/CHANGELOG.md`](communications/CHANGELOG.md)                                                   |
| Google OAuth (Google Workspace)                    | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| Firecrawl runtime wiring                           | `../../api/domains/agents/service.py` (platform-default + per-agent override)                                                                       |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Tests                                              | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_shared_credentials.py`, `../../api/tests/integration/test_slack_config_token.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A tool Integration provider addition or schema change affects request validation, encrypted compatibility, runtime environment/config generation, built-in Skill seeding, UI forms/Zod schemas, and Agent start tests. Platform additions instead use the shipped Platform Plugin seam. Encryption-key changes require an explicit migration/rotation plan because Agent Secrets, Shared Credentials, and Communication Connection credentials depend on the existing key.
