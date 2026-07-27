# Integrations

## Read when

Read before changing provider credential schemas, encryption, Slack app setup, Google OAuth, aai-cli configuration, provider-derived skills, or runtime secret injection.

## Role in the system

Integrations make external services available to an Agent. Agent Secrets hold encrypted provider-specific credentials; agent start converts them into runtime environment, aai-cli secret-store setup, configuration, skill availability, and policy context.

## Supported providers

Provider credential contracts are defined by `SecretProvider` and its content models in `../../api/domains/agents/models.py`. Current providers cover GitHub, Jira, Confluence, Bitbucket, Gmail, Google Calendar, Zoho Mail, and Zoho Calendar.

## Invariants

- Agent Secret payloads are validated against provider-specific schemas before encryption and again after decryption.
- An agent has at most one Agent Secret per provider.
- Duplicate providers in create/update payloads are rejected.
- Read APIs return provider and display label, not credential contents.
- Agent updates validate that remaining skill provider requirements are satisfied. Updating a Skill's provider metadata later does not revalidate existing agents.
- Eligible built-in aai-cli skills are mounted at start when their provider credential is configured.
- Application deployment secrets, per-user Slack configuration tokens, and per-agent Agent Secrets are distinct credential classes with different ownership and lifecycles.

## Slack setup

Per-user Slack configuration tokens support automated Slack app creation. They are encrypted at rest, exposed only as masked previews, validated when saved, and rotated through their refresh token when used. Agent Slack bot/app tokens are separate per-agent credentials.

## Google OAuth

The Gmail OAuth authorize and exchange operations require an authenticated user. The provider callback accepts a signed, typed, short-lived state and forwards the authorization code to the web application; authenticated exchange returns a refresh token. Persistence then occurs through the normal Agent Secret create/update flow.

Server-owned Google client credentials are the default. User-supplied client identity is also supported by the route contract. Gmail requests offline, read-only access.

## Runtime materialization

At start, Agent Service decrypts provider payloads, backfills configured Google client credentials where applicable, builds aai-cli configuration and secret-store setup, injects provider environment, mounts provider skills, and appends tool/integration policy to rendered template content. Provider handling is not complete until both storage validation and runtime materialization are updated.

## Source map

| Concern                                            | Authoritative source                                                                                                                                |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider enum, content schemas, encryption helpers | `../../api/domains/agents/models.py`                                                                                                                |
| Agent Secret persistence and lifecycle             | `../../api/domains/agents/service.py`, `../../api/domains/agents/repository.py`                                                                     |
| aai-cli runtime materialization                    | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                         |
| Built-in skill definitions                         | `../../api/domains/agents/aai_cli_skills/`                                                                                                          |
| Slack configuration token lifecycle                | `../../api/domains/auth/token_service.py`, `../../api/domains/auth/routes.py`                                                                       |
| Gmail OAuth                                        | `../../api/domains/integrations/google_oauth/routes.py`                                                                                             |
| UI credential forms                                | `../../ui/src/features/agents/`, `../../ui/src/features/account/`                                                                                   |
| Tests                                              | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_slack_config_token.py`, `../../api/tests/unit/test_google_oauth.py` |

## Change impact

A provider addition or schema change affects request validation, encrypted compatibility, runtime environment/config generation, built-in skill seeding, UI forms/Zod schemas, and agent start tests. Encryption-key changes require an explicit migration/rotation plan because stored Agent Secrets and Slack configuration tokens depend on the existing key.
