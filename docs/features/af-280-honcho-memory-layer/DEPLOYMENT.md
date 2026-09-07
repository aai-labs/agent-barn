# AF-280 — deployment configuration

Honcho-backed memory is **off by default**. The `postgres-honcho` and `honcho`
Helmfile releases install only when `HONCHO_ENABLED` is `true`, so a deploy with
memory off needs none of the config below — nothing new is required to keep
deploying unrelated changes.

To turn memory **on** for an environment, set `HONCHO_ENABLED=true` for it and
create the config it then requires. A deploy with `HONCHO_ENABLED=true` and any
of these missing fails at render (loudly, naming the missing key), not silently.

## GitHub Variables (Settings → Variables)

Shared across environments unless a per-environment value is needed:

| Variable | Example | Notes |
|---|---|---|
| `HONCHO_ENABLED` | `true` | The switch. Unset/`false` skips all Honcho releases. |
| `POSTGRES_HONCHO_USER` | `honcho` | Honcho's database user. |
| `POSTGRES_HONCHO_DB` | `honcho` | Honcho's database name. |
| `HONCHO_TEXT_MODEL` | `openrouter/z-ai/glm-5.2` | Model for deriver/dialectic/summary/dream. Must be an allowlisted LiteLLM model. |
| `HONCHO_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embedding model LiteLLM routes to. OpenRouter has none, so this must name an embedding-capable provider. |

## GitHub Secrets (Settings → Secrets)

Standard (`deploy.yml`, staging vs prod):

| Secret | Notes |
|---|---|
| `POSTGRES_HONCHO_PASSWORD` | Production Honcho DB password. |
| `STAGING_POSTGRES_HONCHO_PASSWORD` | Staging Honcho DB password. |
| `HONCHO_TELEMETRY_KEY` | Optional. Enables the CloudEvents telemetry the cost split reads; empty is valid but memory cost then reports zero. |
| `STAGING_HONCHO_TELEMETRY_KEY` | Optional, staging. |

Public (`deploy-public.yml`):

| Secret | Notes |
|---|---|
| `PUBLIC_POSTGRES_HONCHO_PASSWORD` | Public Honcho DB password. |
| `PUBLIC_HONCHO_TELEMETRY_KEY` | Optional, as above. |

## Not configured, by design

`HONCHO_LITELLM_KEY` is **not** set here. The Honcho chart mints its own LiteLLM
key in a pre-install hook and publishes it for both Honcho and the API to read.
Set the env only to pin a specific key, which also skips the minting job.

## Turning it on for running agents

`HONCHO_ENABLED=true` deploys the service and points *new* agents at it. Agents
already running keep file-backed memory until they are stopped and started once —
the toggle takes effect on an agent's next start, not on deploy.
