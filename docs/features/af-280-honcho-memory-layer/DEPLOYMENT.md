# AF-280 — deployment configuration

Honcho-backed memory is **off by default**. The `postgres-honcho` and `honcho`
Helmfile releases install only when `HONCHO_ENABLED` is `true`, so a deploy with
memory off needs none of the config below — nothing new is required to keep
deploying unrelated changes.

To turn memory **on** for an environment, set that environment's enable flag and
create the config it then requires. A deploy with `HONCHO_ENABLED=true` and any
of these missing fails at render (loudly, naming the missing key), not silently.

`HONCHO_ENABLED` is the **infrastructure gate** — it stands the service up and
makes shared memory *available*. It no longer moves any Agent on its own: memory
is opt-in per Agent through **memory groups** (a group is a shared memory pool;
adding an Agent to a group turns its shared memory on). So enabling an
environment changes nothing an operator can see until someone creates a group and
adds Agents to it, in the org's Settings → Memory Groups. Managing groups needs
the `memory_group.manage` permission, which the API seeds automatically (a data
migration grants it to org Owners and Admins) — no config below is needed for it.

## GitHub Variables (Settings → Variables)

Shared across environments unless a per-environment value is needed:

> The enable flag is **not** shared: `HONCHO_ENABLED` (production), `STAGING_HONCHO_ENABLED` (staging), and `PUBLIC_HONCHO_ENABLED` (public) are separate, so a normal rollout enables staging first and production later. The DB user/name and model vars below are shared across environments; only the enable flag and the DB password differ per environment.

| Variable | Example | Notes |
|---|---|---|
| `HONCHO_ENABLED` | `true` | The switch (production / k3s main). Unset/`false` skips all Honcho releases. |
| `STAGING_HONCHO_ENABLED` | `true` | The switch for **staging** — independent of production, so memory can be turned on for staging first. |
| `PUBLIC_HONCHO_ENABLED` | `true` | The switch for the **public** cluster (`deploy-public.yml`). |
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
| `HONCHO_TELEMETRY_KEY` | Optional. Enables per-workspace CloudEvents telemetry for analytics. It no longer drives cost — memory cost is the Honcho LiteLLM key's own spend (see below) — so leaving it empty does not zero the cost figure. |
| `STAGING_HONCHO_TELEMETRY_KEY` | Optional, staging. |

Public (`deploy-public.yml`):

| Secret | Notes |
|---|---|
| `PUBLIC_POSTGRES_HONCHO_PASSWORD` | Public Honcho DB password. |
| `PUBLIC_HONCHO_TELEMETRY_KEY` | Optional, as above. |

## Not configured, by design

`HONCHO_LITELLM_KEY` is **not** set here. The Honcho chart mints its own LiteLLM
key in a pre-install hook and publishes it for both Honcho and the API to read.
Set the env only to pin a specific key, which also skips the minting job. This
same key's LiteLLM spend is the pool-level memory cost the Costs page reports.

## Runtime image requirement

Pool-wide recall on Hermes comes from a patch baked into our `hermes-base` image
(the workspace-level dialectic query), so an environment running memory groups
must be on `hermes-base` **≥ 0.2.4**. OpenClaw needs no image change — its
pool-wide recall ships as the `honcho-pool-recall` plugin, which the API writes
into the Agent's config at start. Nothing here changes for a memory-off deploy.

## Turning it on for running agents

Turning memory on is a two-step, opt-in process, not a fleet-wide flip:

1. **Deploy with `HONCHO_ENABLED=true`.** This stands up the service and makes
   memory available; it moves no Agent by itself.
2. **Add Agents to a memory group** (Settings → Memory Groups). An Agent gains
   shared memory only once it is in a group, and the change takes effect on that
   Agent's **next start** — an already-running Agent keeps its current memory
   until it is stopped and started once. Removing an Agent from a group (or
   deleting the group) revokes its access the same way; its past contributions
   stay in the pool.

The schema change is applied by the API's normal Alembic migration on deploy —
no manual step. There is no automatic migration of an Agent's prior file-backed
memory into a pool; joining a group is a fresh start for shared memory.
