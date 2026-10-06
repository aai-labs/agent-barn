# Development and operations

> **Naming note:** the product rebranded from Agent Farm to Agent Barn. Code and deployment identifiers were migrated in that rebrand (`agentbarn_*` metrics, `agentbarn.io` labels, `agentbarn-*` charts/releases/images). Only the Kubernetes namespaces deliberately keep the old name — `agent-farm` and `agent-farm-staging` — because renaming them would strand running workloads; treat those as stable identifiers, not branding. Rationale and layer-by-layer blast radius: [`../adr/2026-08-22-agent-barn-rebrand-with-frozen-namespaces.md`](../adr/2026-08-22-agent-barn-rebrand-with-frozen-namespaces.md).

## Local development

The [README quick start](../../README.md#quick-start) owns dependency,
configuration, start, and stop instructions. Its
[development section](../../README.md#development) covers the native service
topology.

## Database migrations

```bash
make migrate          # upgrade the configured database to head
make makemigrations   # autogenerate a revision after prompting for its message
make rollback         # downgrade the configured database by one revision
make merge-heads      # create a merge revision only when multiple heads exist
```

`make migrate`, `make rollback`, and `make makemigrations` require the database
at `DB_CONNECTION_URL` to be running and reachable. Migrate to the current head
before autogenerating a revision. `make merge-heads` operates on revision files
and does not require a database.

Schema changes require a migration under `../../api/migrations/versions/`.
Review generated migrations before applying them and run the migration check
listed in [`testing.md`](testing.md#verification-commands). Deployment runs
Alembic through the API chart migration hook described in
`../architecture/runtime-and-deployment.md`.

## Checks and tests

Testing and verification commands live in [`testing.md`](testing.md).

## Deployment shape

The deployable services have independent Helm charts. `../../helmfile.yaml.gotmpl` controls release ordering, and `../../.github/workflows/deploy.yml` builds images and applies Helmfile. Read `../architecture/runtime-and-deployment.md` before changing runtime images, agent Kubernetes resources, chart wiring, migrations, or deployment order.

LiteLLM uses a non-overlapping rolling update (`maxSurge: 0`, `maxUnavailable: 1`): the namespace quota cannot accommodate its old and replacement 2Gi pods at once. Upgrades briefly interrupt the proxy while Kubernetes replaces the pod; do not restore the default surge behavior unless the quota is increased first.

## Local Communications reload

Compose and `make dev-api` / `make dev-communications` run the Communications
gateway with a five-second graceful shutdown timeout. Its persistent runtime
control streams otherwise keep Uvicorn waiting indefinitely during a code reload,
leaving accepted Web Chat messages queued. After the timeout, open streams are
cancelled and runtimes reconnect; PostgreSQL retains pending deliveries. If an
already running local gateway is stuck, recreate it with
`docker compose up -d --no-deps communications` to load these launch flags.

## Agent Memory deployment

The gateway runs from the API image as `api.memory_main:app` on port 8003, with
access logging disabled so client paths cannot enter logs. `make dev-api` starts
it alongside the other HTTP processes; `make dev-memory` runs it separately.
For local use set `HINDSIGHT_BASE_URL` to the backend root and `HINDSIGHT_API_KEY`
to its shared API key. Compose starts the gateway; the optional local backend is
enabled separately with the `local-hindsight` profile.
`./run.sh` includes the `memory` service. Its published `MEMORY_PORT` defaults
to 8003; set a distinct port if the product API or another local service uses it.
An Agent needs no messaging connection to view saved memories. A missing bank
returns an empty list, while an absent gateway or unconfigured/unavailable
Hindsight backend produces an unavailable error, including for a new Agent.

To use the local backend, configure these values in the ignored `.env`:

```dotenv
COMPOSE_PROFILES=local-hindsight
HINDSIGHT_BASE_URL=http://hindsight:8888
HINDSIGHT_DB_PASSWORD=<generated URL-safe password>
HINDSIGHT_API_KEY=<generated API authentication key>
HINDSIGHT_LITELLM_API_KEY=<dedicated budgeted LiteLLM virtual key>
MEMORY_LITELLM_KEY_HASHES=<SHA-256 of that virtual key>
```

Initially use a virtual key restricted to `openrouter/openai/gpt-4.1-mini`, with no
Organization team assignment. Keep its hash alongside any retired hashes in
`MEMORY_LITELLM_KEY_HASHES` for cost attribution. `./run.sh` starts the backend
when that profile is enabled. To start it on an already running stack:

```bash
docker compose up -d hindsight-db hindsight memory
docker compose up -d --no-deps api worker communications
```

The local backend uses the pinned Hindsight image and attribution bridge, with
control plane disabled and API authentication enabled. Its Postgres 18 database
has pgvector, an isolated storage network, and its own named volume; neither
backend nor database publishes a host port. The LiteLLM model key and database
password are blanked in the shared application environment, and only the
gateway receives the backend authentication key. Stop preserves database data.
Backups and tested restores remain deferred.
The product API lists an Agent's saved memories through the gateway's separate
viewer under `/memory/view/v1`, addressed by `MEMORY_VIEW_BASE_URL`. `make dev-api`
points it at `localhost`, Compose at the `memory` service, and the chart at the
`<release>-memory` Service; override it only when the gateway lives elsewhere.
The viewer authenticates a short-lived capability signed with the platform signing
key, which the gateway already receives from the shared API Secret; no additional
Hindsight or Kubernetes credential reaches the product API.
Opted-in starts configure Hermes and OpenClaw for automatic recall and retain
alongside native memory. Rebuild the runtime base images to install the pinned
Hindsight clients/plugin before using this integration, then restart opted-in
Agents so they receive the current configuration and fresh credentials. Runtime
startup waits briefly for authenticated gateway health before loading the plugin;
native memory remains available when the gateway is unavailable.

Helmfile leaves the backend and gateway off by default. For an operator-run
Helmfile deployment, set `HINDSIGHT_ENABLED=true`, `HINDSIGHT_DB_PASSWORD`,
`HINDSIGHT_API_KEY`, `MEMORY_RUNTIME_SERVICE_KEY`, and `HINDSIGHT_LITELLM_API_KEY` in `.env.deploy`. Use distinct
database/auth secrets and a budgeted LiteLLM virtual key for the last value.
The deployment workflows do not yet enable this optional release.

This adds `postgres-hindsight` (pgvector/PostgreSQL 18, its own 10Gi PVC) and
Hindsight 0.10.2. Only its API port 8888 is exposed, as ClusterIP; its control
plane is off and API authentication is mandatory. The gateway gets the auth key
through one Secret key reference. The product API holds no Hindsight auth key. A separate
`MEMORY_RUNTIME_SERVICE_KEY`, distinct from `HINDSIGHT_API_KEY`, is provided only
to its internal settings listener and the Hindsight bridge; worker and Agent
pods receive neither.
Rotating `HINDSIGHT_API_KEY` through Helmfile rolls Hindsight and the gateway
through their Secret/auth checksums. Rotating `MEMORY_RUNTIME_SERVICE_KEY` rolls
Hindsight and the product API through their Secret/settings-key checksums.
With a manually managed Secret, restart Hindsight and the gateway after rotating
the Hindsight auth key; restart Hindsight and the product API after rotating the
settings key. Environment variables are read at boot.

Hindsight uses a dedicated platform key for bankless startup verification.
Bank operations resolve an encrypted Organization key on its runtime LiteLLM
team through the internal settings listener. Apply migration `f69a2e0c847d` before deploying
this bridge; keep `AGENT_TOKEN_ENCRYPTION_KEY` stable so existing memory keys
remain decryptable. Apply migration `f03a9c61d872` for the memory-key cleanup
journal. The existing `llm-budget-reconciler` job retries up to 20 remote key
revocations per pass; `make reconcile-llm-budgets` runs the same cleanup locally.
Only hashes are journaled, so cleanup also works after an encryption-key change.
Do not rotate `AGENT_TOKEN_ENCRYPTION_KEY` without migrating encrypted values:
decryption failures return 503 and preserve the existing record. Deliberately
blocked LiteLLM keys also return 503; unblocking requires an operator action.
A confirmed missing key or mismatched team assignment is repaired on settings
refresh, while transient proxy failures never trigger new key issuance.
If both database journaling and remote revocation are unavailable after issuance,
use LiteLLM's `agentbarn_memory` metadata to identify and revoke the orphan;
distributed issuance cannot guarantee cleanup during simultaneous outages.
The internal listener uses the API workload's existing LiteLLM master access
to provision these keys; the Agent gateway needs neither master nor encryption
credentials.
`openrouter/openai/gpt-4.1-mini` is the initial default; Platform Admins can
choose subsequent models in Platform Settings → Agent Memory. Do not share this key with Agents or attach it to
an Organization team. The chart runs a pinned startup bridge that sends each
operation's canonical bank as the model request's `user` field; the existing cost
CronJob attributes LiteLLM's billed calls to that Organization without reading
Hindsight traces. Helmfile derives the current key's SHA-256 hash into
`MEMORY_LITELLM_KEY_HASHES`. On rotation, retain the old hash in that comma-separated
`.env.deploy` setting so late/replayed calls keep their attribution. Only hashes,
never the platform key, enter the API's shared Secret.

For a locally operated Hindsight instance, run `helm/hindsight/files/start_hindsight.py`
with the pinned image's Python, external database, OpenAI provider, and normal
Hindsight auth/LLM environment. Set `MEMORY_LITELLM_KEY_HASHES` in `.env` to the
SHA-256 of its dedicated LiteLLM key. The standard upstream entrypoint does not
install our bridge and cannot attribute memory spend per Organization.

The enabled gateway chart requires attribution key hashes. Keep the existing
cost-sync CronJob (every 15 minutes) and LLM-budget-alerts snapshot job (every
5 minutes) running. All Organizations need a successful cost sync and a current
runtime snapshot before retain/reflect become available. The local `./run.sh`
stack runs cost sync immediately and every 15 minutes through Compose's
`cost-sync` service. Restart that service after changing its Python code or
environment. Compose's `budget-snapshots` service refreshes runtime snapshots immediately
and every five minutes. Restart it after changes to code or environment. Host-run setups also need cost sync
on its schedule (`cd api && uv run python -c "from api.domains.costs.sync import main; main()"`). See
[Costs](../features/costs.md#organization-llm-budgets) for freshness
requirements, 429/503 behavior, and the observed-spend limitation. The gateway
uses persisted accounting and needs no LiteLLM master key or Kubernetes credentials.

When memory is enabled, the chart deploys `agentbarn-api-memory-purge` every five
minutes with `Forbid` concurrency and a 280-second pod deadline. It holds only the
product database URL and Hindsight auth key, mounts no kubeconfig, and disables
service-account token mounting. Keep it running while tombstones remain; disabling
the optional release pauses physical cleanup.

For local operation, schedule `make purge-agent-memory` with `DB_CONNECTION_URL`,
`HINDSIGHT_BASE_URL`, and `HINDSIGHT_API_KEY`. Repeating runs after a failure or
restart is safe. The cleanup/repair launchers supply inert creation-budget defaults
because they never create Organizations or Agents; no deployment budget settings or
user-authentication credentials are required. Inspect `agent_memory_purge.last_error`, `attempts`,
`next_attempt_at`, and `last_cleaned_at` for progress without reading memory content.
The [deletion contract](../features/agent-memory.md#deletion-cleanup) owns retry
leases, runtime limits, and hourly sweeps for previously accepted Hindsight work.
Downgrading `a63e8c941d20` drops pending cleanup; it cannot restore removed grants.
Complete cleanup before retiring this table/job. Backups and restore work are
deferred in the [delivery log](../features/agent-memory/CHANGELOG.md).

When upgrading from shared writes tagged with `agent:<id>`, repair each affected
Organization using `uv run --project api python -m api.domains.agent_memory.retag_shared
<organization_id>` from the repository root with `HINDSIGHT_BASE_URL` and
`HINDSIGHT_API_KEY`. Stop shared writes and let outstanding extraction and consolidation work
finish before this one-time repair. Repeat the command after any earlier
extraction work finishes. It reports document
counts only. The [memory upgrade contract](../features/agent-memory.md#upgrade-legacy-shared-ownership-tags)
owns tag replacement and observation invalidation. This does not require a
Postgres schema migration.

Run `make check-memory` with Helm installed to validate both enabled and disabled
renders without connecting to a cluster. The API CI workflow runs the same check.

### Operating Platform Agent Memory model settings

Apply migration `d83f291bc7a0` before deploying the settings API. Deploy both
bridge files (`start_hindsight.py` and `memory_model.py`) and set
`AGENTBARN_MEMORY_SETTINGS_URL` to the API workload's internal port 8004
`/memory/runtime/v1/model` endpoint. Set `MEMORY_RUNTIME_SERVICE_KEY` to a
separate random credential and supply it to the bridge as
`AGENTBARN_MEMORY_SETTINGS_KEY`; never reuse Hindsight's API auth key. Compose and Helm supply the internal URL. Existing backends need one
restart to install the bridge; subsequent settings changes need none. The
endpoint is absent from the public product API and is not published by Compose
or routed through ingress. The API workload receives only the settings key
through an explicit Secret reference; Agent pods do not.

Set `MEMORY_LITELLM_ACTIVE_KEY_HASH` when retaining multiple attribution hashes.
Helmfile derives it from the currently configured dedicated key; Compose
operators supply it in `.env`. With a single hash the API infers the active one.
Settings saves expand only that key's model allowlist and preserve prior models,
budgets, and spend. On key rotation provision the persisted model, startup
fallback, and models needed by in-progress operations on the new key. Keep
retired hashes for delayed cost attribution.

Set `MEMORY_DEFAULT_MODEL` in `.env` (Compose) or `.env.deploy` (Helmfile) to
customize the initial model. Both deployments use that one setting for the API
default and Hindsight startup model. When using charts directly, set API
`memory.defaultModel` and Hindsight `llm.model` to the same value. Gateway outages
retain the last known selection,
or the startup model before the first successful fetch. A schema downgrade drops
the persisted choice.

### Integrating Agent Memory with staging spend limits

Migration `e94b17c62a30` joins the memory and self-service spend-limit histories.
Existing local databases can upgrade in place; applied memory revisions are kept
rather than squashed, preserving saved records, grants, and development data.
Migration `e81c2a97b4f3` also joins the memory team-key history with staging's
Personal API Keys history. Run migrations before restarting API processes after integrating staging. Both
`ORGANIZATION_DEFAULT_LLM_BUDGET_USD` and `AGENT_DEFAULT_LLM_BUDGET_USD` are required;
set them before startup. The new local `budget-snapshots` service uses the same
`--watch` loop as the budget job entry point, refreshing every five minutes.

## Organization LLM budgets

Every Organization has a Spend Ceiling, set by a Platform Administrator through
`PUT /platform/organizations/{id}/llm-budget`; beneath it the Organization's Owners and
Admins set a lower limit of their own, a default for their Agents, and a limit per
Agent. The behaviour contract is in
[Costs](../features/costs.md#organization-llm-budgets).

Two deployment settings are **required** — the API, its worker, every CronJob and the
migration job all refuse to start without them:

| Setting | Meaning |
| --- | --- |
| `ORGANIZATION_DEFAULT_LLM_BUDGET_USD` | The ceiling a new Organization starts with. The migration that introduced it also gave it to every existing Organization that had none. |
| `AGENT_DEFAULT_LLM_BUDGET_USD` | The limit an Agent is held to until its Organization sets a default or the Agent its own. Must not exceed the Organization default. |

Deploys read them from repository variables, following the usual prefixes:
production uses the names above, staging `STAGING_ORGANIZATION_DEFAULT_LLM_BUDGET_USD` /
`STAGING_AGENT_DEFAULT_LLM_BUDGET_USD` (falling back to the production ones when unset),
and the public deployment `PUBLIC_ORGANIZATION_DEFAULT_LLM_BUDGET_USD` /
`PUBLIC_AGENT_DEFAULT_LLM_BUDGET_USD`. They reach the chart's
`organizationLlmBudgets.defaultOrganizationUsd` / `defaultAgentUsd` through
`helmfile.yaml.gotmpl` and render into the shared API Secret; the chart refuses to
render without them, so a deploy with either variable unset fails before anything
changes.
Local runs read them from `.env`, and the API test suite sets its own in
`api/tests/conftest.py`.

No Agent restart is required: a change takes effect as soon as it is saved.
`budget_usd` is a non-negative finite number and is required on the ceiling — it can
be changed but not cleared, so "no practical limit" is a very large amount.
`budget_duration` is one of `1d`, `7d` or `30d`, defaulting to `30d`; LiteLLM renews
these on calendar boundaries (next midnight, next Monday, the 1st of the month), which
is what keeps the Organization and its Agents renewing together. Changing only an
amount preserves spend and the renewal date; changing the window moves the next
renewal without resetting spend.

**Rollout (AF-337): no manual step is needed.** LiteLLM keeps one running spend total
per key and per team and only zeroes it when a window renews, so a key or team that
was never capped carries everything it has ever spent into its first window. Three
things keep that from refusing anyone at rollout:

- The migration gives every existing Organization without a ceiling $10,000 a month
  rather than `ORGANIZATION_DEFAULT_LLM_BUDGET_USD`: high enough that its team's
  lifetime spend refuses nobody, while the team gets a window and renews on the 1st.
- It sets every existing Organization's default Agent limit to its ceiling (that
  $10,000, or the ceiling it already had from AF-303), so existing Agents are not held
  to `AGENT_DEFAULT_LLM_BUDGET_USD`; the team stays the only limit that binds.
- The first time a limit is written to a key that has never had a window (every key
  created before AF-337), the API zeroes that key's spend first
  (`POST /key/{key}/reset_spend`), so its cap measures from then. This happens on the
  reconciler's first pass after the deploy. Spend logs, and so cost records, are
  untouched.

From the first renewal on, team spend is per window, and a platform administrator can
set a real limit without any reset. One edge case remains: LiteLLM cannot zero a
single team, so an Organization without a ceiling whose team has already spent more
than $10,000 in total, or one given a real limit before its first renewal, is measured
against lifetime spend until the 1st. LiteLLM's only team-wide option is
`POST /global/spend/reset`, which zeroes every key and team at once.

Saving a limit writes the row first and then pushes it to LiteLLM. A
proxy failure returns `502` with the amount already stored, because losing an
administrator's setting because the proxy blinked is worse than a delayed push. The
`<release>-llm-budget-reconciler` CronJob pushes stored limits onto every team and
Agent key every 15 minutes to repair exactly that kind of drift, logging
`Organization LiteLLM budgets reconciled`. Like the other reconcilers it runs under
`concurrencyPolicy: Forbid`, so one runner regardless of API replica count, and the
API itself never contacts the proxy at startup. A budget saved while the proxy was
unreachable is therefore applied within one interval rather than at the next restart.
Run either pass by hand with `make reconcile-llm-budgets` or `make run-llm-budget-alerts`.

`ORGANIZATION_LLM_BUDGET_ALERT_THRESHOLDS` sets the percentages at which an
Organization's Owners and Admins are notified — comma separated, each between 1 and
100, defaulting to `80,100`. A malformed list refuses to boot rather than quietly
alerting nobody. The value is read by the API and by the
`<release>-llm-budget-alerts` CronJob, which runs every 5 minutes over every
Organization and every Agent key. The same thresholds apply to an Agent's own limit,
whose alerts go to its creator and Owners. Alerting is informational: the limit is
enforced in the request path, so the interval only bounds how late someone is told.

Agents created before an Organization had a team carry none on their key, so the
Organization's limit does not bind them until they are enrolled. A Platform
Administrator does that from the Organization's page, where uncovered Agents are
named beside the limit controls and the button reports anything it could not enroll.
Historical pre-enrollment spend stays in reports but is not added to the new team
counter.

## Transactional email

Invites, password resets, and agent lifecycle notifications send through
[Cloudflare Email Service](https://developers.cloudflare.com/email-service/api/send-emails/rest-api/)
(`POST https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send`,
Bearer token). `../../api/infrastructure/email/client.py` is the only place that
talks to the provider; `EmailService` above it is transport-agnostic.

- **`CLOUDFLARE_ACCOUNT_ID`** and **`CLOUDFLARE_API_TOKEN`** are GitHub secrets; **`SENDER_EMAIL`** is a GitHub variable. All three flow through `helmfile.yaml.gotmpl` into the API chart's Secret. Unset leaves delivery disabled: sends are logged and no-op rather than raising.
- The API token MUST carry the **Email Sending: Edit** permission on the account in `CLOUDFLARE_ACCOUNT_ID`.
- `SENDER_EMAIL`'s domain MUST be onboarded for Email Sending in that account,
  or Cloudflare rejects sends from it. Add domains under **Compute → Email
  Service → Email Sending** in the Cloudflare dashboard; DNS propagation can
  take up to 24 hours.
- **Each environment sends from its own `mail.`-style subdomain**, never the root domain — production `noreply@mail.agentbarn.dev`, staging `noreply@mail-staging.agentbarn.dev`. Sending reputation is scored per-domain, so this keeps a damaged reputation away from the root domain that serves the website and logins, and away from other environments.
- **`SENDER_EMAIL` is the only per-environment value.** `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are shared references reused across both environments, because one `Email Sending: Edit` token covers every verified domain on the account. Consequence: rotating that token takes both environments down at once. A token cannot be scoped to a single sending domain, so per-environment tokens would buy revocation independence but not access isolation.
- **[Sending quotas](https://developers.cloudflare.com/email-service/platform/limits/)
  are account-scoped and can change with account standing and
  sending behavior.** Staging and production share that quota, so check the
  account's current limit before a staging load test or send loop that could
  starve real invites.
- Message size is capped at 5 MiB including attachments. The inline barn logo is sent as a base64 attachment with `disposition: "inline"` and a snake_case `content_id` matching the `cid:` reference in the MJML templates — `contentId` is the Workers binding's spelling and is not accepted by the REST API.

## Per-Agent email addresses

Agents reachable by email get their own address on a dedicated subdomain, receive mail through a Cloudflare Email Worker, and reply through the same Email Sending path as transactional mail. Rationale for the Worker: [`../adr/2026-08-31-cloudflare-worker-for-inbound-email.md`](../adr/2026-08-31-cloudflare-worker-for-inbound-email.md).

- **`AGENT_EMAIL_DOMAIN`** (GitHub variable, `STAGING_` variant) and **`EMAIL_INBOUND_SECRET`** (GitHub secret, `STAGING_` variant) flow through `helmfile.yaml.gotmpl` into the API chart's Secret. Unset leaves the Email platform refusing new Communication Connections; nothing else changes, so an environment whose Cloudflare domain is not yet onboarded can safely leave them blank. Both are read by the **Communications deployment** as well as the API — it mounts the same Secret with `envFrom`, so no separate wiring exists.
- Unlike the shared `CLOUDFLARE_API_TOKEN`, `EMAIL_INBOUND_SECRET` is **per-environment**, and the two environments' values **must differ**: it is the only credential guarding mail injection, so a staging leak must not be usable against production. Generate with `openssl rand -hex 32`.
- **The subdomain must be onboarded twice** — once under **Compute → Email Service → Email Routing** (inbound MX) and once under **Compute → Email Service → Email Sending** (the `From` address). They are separate flows with separate DKIM selectors (`cf2024-1._domainkey` and `cf-bounce._domainkey`). Sending verification can take up to 24 hours, and until it is Verified inbound works while every agent reply fails with a `550`-class error — a split that reads like a reply bug rather than a provisioning gap.
- A subdomain is added from **inside the apex domain's settings** (Email Routing → select the apex → Settings → Subdomains), not as a new domain of its own. There is no top-level "onboard a subdomain" action.
- **Subaddressing must be switched on explicitly** at **Email Routing → Settings**. It is **off by default**, and until it is enabled `agent+<slug>-<token>@…` matches no rule at all: the sender gets `550 5.1.1 Address does not exist` and **nothing is written to the Email Routing activity log**, because no rule ever matched. A bounce with an empty activity log is the signature of this being off.
- **One routing rule serves every agent.** With subaddressing enabled, a single custom-address rule for `agent@agents.agentbarn.dev` → Worker matches `agent+<slug>-<token>@agents.agentbarn.dev` and preserves the `+tag` in `message.to`. The local part must equal `AGENT_EMAIL_MAILBOX` (default `agent`). No Cloudflare API call happens when an Agent is created. Catch-all is zone-apex only and cannot be used on a subdomain; making the subdomain its own zone is Enterprise-only.
- The Worker must exist before the rule can point at it, so deploy it first — the destination picker only lists deployed Workers.
- **One domain, Worker and variable set per cluster.** A domain carries a single Email Routing rule, so two clusters cannot share one: whichever Worker the rule names receives every message, and the other cluster's addresses resolve against a database that has never heard of them — answered `202` with an empty acceptance, which Email Routing reports as "handled".

  | Domain | Cluster | Wrangler env | Worker | Variable / secret |
  |---|---|---|---|---|
  | `agents-staging.agentbarn.dev` | staging (k3s) | `staging` | `agentbarn-email-inbound-staging` | `STAGING_AGENT_EMAIL_DOMAIN` / `STAGING_EMAIL_INBOUND_SECRET` |
  | `agents-prod.agentbarn.dev` | prod (k3s) | `prod` | `agentbarn-email-inbound-prod` | `AGENT_EMAIL_DOMAIN` / `EMAIL_INBOUND_SECRET` |
  | `agents.agentbarn.dev` | cloud (Talos) | `cloud` | `agentbarn-email-inbound` | `PUBLIC_AGENT_EMAIL_DOMAIN` / `PUBLIC_EMAIL_INBOUND_SECRET` |

  All three pairs must differ. The Worker environment names its **cluster**, never a role: while `production` meant the k3s cluster in `deploy.yml` and the Talos cluster in `wrangler.toml`, a Worker was published aimed at one and handed the other's secret, and every production message was rejected `401`.
- **The Worker deploys through CI**, not by hand, and **each environment's Worker is published by the workflow that deploys the cluster it posts into**. `deploy.yml`'s `deploy-worker` publishes `staging` and `prod` when `workers/**` changed; `deploy-public.yml`'s publishes `cloud` on a release tag, gated on `PUBLIC_AGENT_EMAIL_DOMAIN` being set so an environment without agent email is unaffected. Both run only after their cluster deploy succeeds — the Worker posts into the product API, so the cluster must already hold the matching secret. Pull requests run `wrangler deploy --dry-run` for all three through `ci.yml`, which needs no Cloudflare credentials. This requires **`CLOUDFLARE_WORKERS_TOKEN`** (account-owned, scoped to `Workers Scripts: Edit`), deliberately separate from the `Email Sending: Edit` token so one leak cannot both send mail as the domain and replace the Worker receiving it.
- **Both the cluster deploy and the Worker publish fail when an environment's domain is configured but its secret is empty**: the API rejects a blank configured secret outright, so an unset value bounces every inbound message with `401` rather than degrading. Each guard selects its secret with a shell `case` over separately passed values, never `A && B || C`, which yields `C` whenever `B` is empty and would validate the wrong environment's secret. `worker.yml`'s guard exports the resolved value to `$GITHUB_ENV` and the publish step consumes that, so the value checked is provably the value uploaded — a second expression could not express three environments and would reintroduce the drift.
- **The Worker is built from the commit being deployed.** `deploy-public.yml` passes the resolved release sha to `worker.yml`, so a `workflow_dispatch` of an older tag republishes that tag's Worker rather than whatever the dispatch ref points at.
- **`EMAIL_INBOUND_SECRET` is written to the Worker and the cluster by the same run**, from one GitHub secret, so the two cannot drift. **Rotating it has a brief window**: the two are updated by consecutive steps, so mail arriving between them bounces `401`. To rotate without that, set the Worker's copy first with `wrangler secret put EMAIL_INBOUND_SECRET --env <env>`, then update the GitHub secret and deploy.
- **Break-glass manual deploy** (a broken pipeline, or first-time bring-up before the token exists): `cd workers/email-inbound && pnpm install && pnpm exec wrangler deploy --env <staging|prod|cloud>`. Prefer CI — a hand-deployed Worker can drift from the committed source with nothing detecting it.
- **A routing rule names one specific Worker, and CI cannot repoint it.** When an environment's rule was created against a differently-named Worker — a `--env local` one used for tunnel testing, say — publishing through CI creates the correctly-named Worker but leaves the rule pointing at the old one, so mail keeps going to the stale Worker. Cut over in this order: **let CI publish first, then repoint the rule's destination, and only then delete the old Worker.** Deleting first leaves the rule aimed at nothing and bounces every message for that domain.
- **Delete `--env local` Workers when finished.** They point at a `cloudflared` tunnel that stops existing when the laptop closes, and an account accumulating them is an account where it is easy to point a rule at the wrong one.
- Deploys publish a **new version of one Worker per environment**, not new Workers; Cloudflare retains ~100 versions for `wrangler rollback`. That is why the deploy is path-filtered: unrelated merges would otherwise consume the rollback history.
- **Local k3d testing**: a Worker runs on Cloudflare's edge and cannot reach a local cluster. Either expose the Communications service with a tunnel (`cloudflared tunnel`) and point `INBOUND_URL` at it, or skip the Cloudflare hop entirely and exercise the whole Agent Barn path by posting the Worker's JSON straight at `/communications/v1/webhooks/email/inbound` with the configured bearer token.
- **Agent mail draws on the same account-wide sending quota** as invites, password resets, and lifecycle notifications, across both environments. A chatty Agent can starve real user invites; see the quota note above.
- Relevant limits: 200 routing rules per domain, 200 verified destination addresses per account, 30 domains per zone, 25 MiB inbound message size.

## Native runtime gateway rollout

- **`COMMUNICATIONS_NATIVE_PLATFORMS`** is one shared GitHub variable containing a comma-separated native runtime Platform allowlist. Set it to **`slack,discord`** to enable the Hermes/OpenClaw native Slack and Discord gateways in every deployment workflow. It flows through `helmfile.yaml.gotmpl` into the API chart's shared Secret, so both the API and Communications processes receive the same cutoff.
- Empty is the rollback setting: all Platforms remain on the Communications Gateway. Restart affected Agents after deploying a change so their runtime configuration is rebuilt.

## Staging environment

Staging is a fully separate stack in its own namespace (`agent-farm-staging`),
driven off the `staging` branch rather than a GitHub Environment. `main` remains
the k3s testing-ground deploy source. Hosted public production is the Talos
cluster via release tags; see [Public cluster (Talos)](#public-cluster-talos).
See
[`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md)
for why staging is a namespace.

- **Trigger:** `deploy.yml` runs on pushes to `staging` and `main`, and via `workflow_dispatch`; it resolves `NAMESPACE`/`ENVIRONMENT`/image-tag suffix/hosts/secrets from `github.ref_name`. Dispatching from anything other than `staging` or `main` fails the workflow.
- **Images:** all four images (api, ui, hermes-base, openclaw-base) get a `-staging` tag suffix on staging; staging never pushes `:latest`, since each environment builds its own base images and their installed contents can diverge.
- **Change detection:** `deploy.yml` compares the current commit with the latest successful deploy run for the same branch. A failed deploy does not advance that baseline, so a later fix rebuilds every component changed since the last successful deploy. If no valid baseline can be found, or the workflow is dispatched manually, all four images are built.
- **Secrets/vars:** every per-env value uses a `STAGING_`-prefixed GitHub secret or variable, selected by a `github.ref_name == 'staging' && secrets.STAGING_X || secrets.X` ternary in `deploy.yml`. Shared references (registry, `OPENROUTER_API_KEY`, Google OAuth client, DB user/db names, and the Cloudflare email account/token) are reused as-is. Email follows the standard convention: only `STAGING_SENDER_EMAIL` differs, pointing staging at its own `mail-staging.` sending subdomain.
- **RBAC bootstrap:** the staging namespace and its deploy identities are
  provisioned out of band. Do not use `deploy.sh` as a staging entry point: it
  always applies `k8s/agent-farm-user.yaml` for `agent-farm`. The current
  `k8s/agent-farm-user.staging.yaml` defines `agent-farm-user`, while
  `deploy.yml` selects `agent-farm-staging-user` for the LiteLLM key job; align
  those names before treating that manifest as workflow bootstrap automation.
- **Isolation invariant:** the API pod's `K8S_NAMESPACE` env var (from `{{ .Release.Namespace }}` in the API chart) must stay wired, or the staging API would create agent workloads in the prod namespace instead of its own.

## Public cluster (Talos)

Hosted public Agent Barn runs on the dedicated Talos cluster, not on k3s. k3s (`staging` / `main` via `deploy.yml`) stays the AAI Labs testing ground. Public deploys only from a `vX.Y.Z` tag via `../../.github/workflows/deploy-public.yml`. Rationale: [`../adr/2026-08-27-public-cluster-release-tags.md`](../adr/2026-08-27-public-cluster-release-tags.md).

- **Trigger:** pushing a tag matching `v*.*.*`, or a `workflow_dispatch` with an
  existing tag. A manual dispatch uses the selected branch's Helmfile and
  configuration (normally `main`); API/UI use the requested release tag, while
  the checked-in image context and runtime `VERSION` values come from that tag's
  commit. Set `skip_build` to reuse images already in the registry.
- **Images:** API and UI use the git tag; Hermes and OpenClaw use their
  independent `VERSION` files. The workflow also publishes a moving `:latest`
  alias for each image, but Helmfile deploys the explicit release/runtime tags.
  Nothing in this workflow writes to `registry.k8s.aai-labs.com`.
- **Registry:** `PUBLIC_REGISTRY_URL` (`registry.agentbarn.dev`). Do not reuse the k3s registry password or R2 bucket.
- **Namespace:** still `agent-farm` so helmfile and `k8s/agent-farm-user.yaml` apply unchanged. This is a different cluster, so it does not collide with k3s.
- **Secrets/vars:** every public-only value is `PUBLIC_`-prefixed. Postgres **user/db names**, `AGENT_DEFAULT_MODEL` / `AGENT_MODEL_ALLOWLIST`, the Cloudflare email account/token, and the Google OAuth client are reused. OpenRouter, Firecrawl, Slack webhook, DB passwords, and signing keys are **not** reused — copy a value into a `PUBLIC_` secret only when that sharing is intentional.
- **Kubeconfig:** `PUBLIC_KUBECONFIG_B64` must reach the Talos API (`https://<cp-1>:6443`). There is no bastion tunnel. `PUBLIC_POD_KUBECONFIG_B64` is what the API pod uses to manage agents; if unset, the workflow falls back to the deploy kubeconfig. Prefer a namespace-scoped kubeconfig for the pod, as on k3s.
- **Storage:** `PUBLIC_STORAGE_CLASS`. Intended value is `rook-ceph-block-main`. Use `local-path` only while Ceph has no OSDs — postgres then dies with the node that holds the volume.
- **Hosts:** `PUBLIC_UI_HOST` is `cloud.agentbarn.dev` (not `app` — that hostname stays on k3s). Product Grafana is `grafana-app.agentbarn.dev`, not cluster `grafana.agentbarn.dev`.
- **RBAC bootstrap:** the deploy kubeconfig is cluster-admin, so the workflow applies `k8s/agent-farm-user.yaml` (creates the namespace) before helmfile.
- **Release command:** set `RELEASE_TAG` to the new `vX.Y.Z` tag, then run this
  from the release commit already on `main`:

```bash
: "${RELEASE_TAG:?Set RELEASE_TAG to the new vX.Y.Z tag}"
git tag "$RELEASE_TAG"
git push origin "$RELEASE_TAG"
```

### Public GitHub variables

| Variable | Intended value |
|---|---|
| `PUBLIC_REGISTRY_URL` | `registry.agentbarn.dev` |
| `PUBLIC_REGISTRY_USERNAME` | platform registry user (`admin`) |
| `PUBLIC_API_HOST` | `api.agentbarn.dev` |
| `PUBLIC_UI_HOST` | `cloud.agentbarn.dev` |
| `PUBLIC_WEB_APP_URL` | `https://cloud.agentbarn.dev` |
| `PUBLIC_GRAFANA_HOST` | `grafana-app.agentbarn.dev` |
| `PUBLIC_SENDER_EMAIL` | `noreply@mail.agentbarn.dev` |
| `PUBLIC_AGENT_EMAIL_DOMAIN` | `agents.agentbarn.dev`. Unset leaves agent email inert and skips the Worker publish |
| `PUBLIC_STORAGE_CLASS` | `rook-ceph-block-main` (or `local-path` until Ceph OSDs exist) |

### Public GitHub secrets

Generate new values; do not paste k3s `POSTGRES_*` / signing keys. Encode a
kubeconfig portably with
`base64 < path/to/kubeconfig | tr -d '\n'`.

| Secret | What |
|---|---|
| `PUBLIC_KUBECONFIG_B64` | Talos kubeconfig (deploy identity) |
| `PUBLIC_POD_KUBECONFIG_B64` | Optional. API pod identity; defaults to the deploy kubeconfig |
| `PUBLIC_REGISTRY_PASSWORD` | `registry.agentbarn.dev` password |
| `PUBLIC_POSTGRES_APP_PASSWORD` | New |
| `PUBLIC_POSTGRES_LITELLM_PASSWORD` | New |
| `PUBLIC_POSTGRES_FIRECRAWL_PASSWORD` | New |
| `PUBLIC_LITELLM_MASTER_KEY` | New (`sk-` + random) |
| `PUBLIC_SECRET_SIGNING_KEY` | New |
| `PUBLIC_AGENT_TOKEN_ENCRYPTION_KEY` | New Fernet key |
| `PUBLIC_PLATFORM_ADMIN_CREDENTIALS` | `email:password` (API policy: 8+, upper, lower, digit; `openssl rand -hex` is not enough) |
| `PUBLIC_GRAFANA_ADMIN_PASSWORD` | Product Grafana (not cluster Grafana) |
| `PUBLIC_MONITORING_WEB_PASSWORD` | Basic auth on Prometheus/Alertmanager; 12+ alphanumeric (`openssl rand -hex 16`) |
| `PUBLIC_FIRECRAWL_API_KEY` | New (this cluster's Firecrawl) |
| `PUBLIC_OPENROUTER_API_KEY` | Prefer a dedicated key so public traffic is not the testing quota |
| `PUBLIC_SLACK_ALERTS_WEBHOOK_URL` | `#alerts` or a public-specific channel |
| `PUBLIC_EMAIL_INBOUND_SECRET` | New (`openssl rand -hex 32`). Required once `PUBLIC_AGENT_EMAIL_DOMAIN` is set, and must differ from the staging and k3s values |

Shared with k3s (already present): `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_WORKERS_TOKEN`, and
`GOOGLE_CLOUD_CLIENT_SECRET`.

## Versioning and releases

The public product release is identified by a `vX.Y.Z` git tag, which pins the
API and UI images as one deployable bundle. Charts and runtime base images keep
independent versions:

- Chart `version` is the packaging version. Bump it when chart templates or values change, independently of application code.
- `hermes-base/VERSION` and `openclaw-base/VERSION` identify immutable runtime
  image contents. Bump the matching file when its Dockerfile, upstream runtime
  pin, resolved `aai-cli` revision or other build dependency, or a file copied
  into the image changes.
  The Dockerfiles currently resolve `aai-cli` from its public default branch,
  so rebuilding after that branch moves is a content change and requires a new
  runtime version. Workflow, smoke-test, and runtime-plugin-only changes do not
  otherwise alter the image and need no version bump.

Rules:

- API and UI image tags are explicit deployment inputs (`API_IMAGE_TAG`, `UI_IMAGE_TAG`), not chart metadata.
- Bump chart versions late, ideally immediately before the PR, to reduce merge conflicts, when chart packaging actually changed.
- `../../.github/workflows/deploy.yml` builds API and UI images under moving environment tags and passes those tags into Helm via `API_IMAGE_TAG` and `UI_IMAGE_TAG`: `latest` on `main`, `latest-staging` on `staging`. Branch deploys no longer depend on chart `appVersion` bumps.
- Public hosted deploys (`../../.github/workflows/deploy-public.yml`) pin API/UI to the git tag (`vX.Y.Z`) on `registry.agentbarn.dev`. They never move k3s `latest` tags.
- Runtime `VERSION` tags MUST NOT be reused for different image contents:
  local loading skips a tag already present in k3d, and release workflows
  publish that exact tag. The workflows do not enforce registry immutability,
  so verify or bump the version before any published rebuild.
- Manual/bundled release flows also pass explicit API/UI tags rather than reading them from chart metadata.
- LiteLLM, PostgreSQL, and monitoring charts run upstream images; bump only chart `version` when their chart templates change.

Documentation-only changes do not change a service image and do not require a service image-tag change.

## Monitoring stack

`../../helm/monitoring/` (plain namespace-scoped Prometheus + Grafana + Alertmanager) deploys with the regular Helmfile sync. Operational notes:

- Everything the chart renders is namespaced and it creates no RBAC objects at
  all (the tenant deployer may not create Roles/RoleBindings). Prometheus and
  kube-state-metrics run under the environment-selected tenant ServiceAccount,
  which must already have namespaced read; Grafana is the only ingress-exposed
  pod and runs without a ServiceAccount token. This is what makes the stack
  deployable on the shared cluster by the namespace-scoped deployer. Note the
  dashboards ConfigMap is deliberately not labeled `grafana_dashboard` — the
  cluster's central Grafana imports that label from every namespace.
- Required GitHub Actions config: secrets `SLACK_ALERTS_WEBHOOK_URL` (incoming webhook for `#alerts`), `GRAFANA_ADMIN_PASSWORD`, and `MONITORING_WEB_PASSWORD` / `STAGING_MONITORING_WEB_PASSWORD` (basic auth on Prometheus and Alertmanager, which agent pods can otherwise reach in-namespace; 12+ alphanumeric, e.g. `openssl rand -hex 16`); variable `GRAFANA_HOST` (DNS must resolve for the http01 challenge). The credits metric reuses the existing `OPENROUTER_API_KEY` secret (the API polls `GET /key` for the key's `limit_remaining`); for `OpenRouterCreditsLow` to be meaningful, set a credit limit on that key at openrouter.ai — an unlimited key reports `+Inf`.
- Monitoring verification and its prerequisites live in
  [`testing.md`](testing.md#verification-commands). CI selects
  `.github/workflows/monitoring.yml` for `helm/monitoring/**` changes.
- Agents that were already running before the monitoring deploy are invisible to Prometheus until stopped and started once: the `/metrics` sidecar script and the Service labels the agent scrape config relies on (`agentbarn.io/component`, `agent-name`, `org-name`) only apply when the API rebuilds the agent's resources in the start flow. When only the scrape label is missing (e.g. agents predating the agentfarm→agentbarn rebrand), no restart is needed — patch the Service labels in place, which does not disturb running pods: `kubectl -n NAMESPACE label svc -l agentfarm.io/component=agent agentbarn.io/component=agent --overwrite`.
- The product API also queries this Prometheus, for Agent CPU and memory ([`resource-usage.md`](../features/resource-usage.md)). helmfile passes `MONITORING_WEB_PASSWORD` straight to the `agentbarn-api` release (`prometheus.password`), so the API and the monitoring release always share one password, and rotating it rolls the API pods too. It is passed directly, not read from the `monitoring-web-auth` Secret, because the monitoring release deploys after the API. With the password unset, or Prometheus unreachable, the Resource usage views say so and everything else keeps working.
- Agents report CPU and memory from their healthz script, which ships in the Agent's ConfigMap. After a deploy that changes it, a running Agent shows "Restart this agent to start reporting CPU and memory" (and "update available") until it is stopped and started once.

## Operational safety

- Treat signing-key and encryption-key rotation as migrations: existing tokens or encrypted values depend on the current keys.
- Treat a stricter provider content schema like a data migration too: every Agent start re-validates stored Agent Secrets and Shared Credentials, so rows saved under the old rule stop their Agents' starts (with a 400 naming the integration) until re-saved. Before deploying such a change, run `python -m api.scripts.check_secret_contents` in each environment's API pod. It is read-only, lists failing rows by id and provider without printing values, and exits non-zero when any fail.
- Verify migration and secret-hook behavior when changing API chart startup.
- Keep runtime/platform differences explicit when changing Hermes, OpenClaw, Slack, Teams, Telegram, or Discord deployment configuration.
- The content-free Communications operation journal is retained for
  `COMMUNICATION_JOURNAL_RETENTION_DAYS` days (default `31`, bounded to
  `1`–`3650`). Its supervisor prunes expired entries; changing this window is
  an operational configuration change, not a release-version change.
- On k3s, use `deploy.yml` rather than manually publishing mutable `latest` tags. Public hosted releases are git tags via `deploy-public.yml`.

### Agent Restore Points

- **The API's cluster identity needs `batch/jobs` (`create`, `get`, `list`, `delete`) and
  `pods/log` (`get`).** Capture and restore run as Jobs, and their status and archive manifest
  are read back from the Job pod's logs. `k8s/agent-farm-user.yaml` and its staging sibling
  grant both, but the API pod authenticates with the kubeconfig in `POD_KUBECONFIG_B64`, not
  that ServiceAccount — on a cluster where those are different identities, verify with
  `kubectl auth can-i create jobs.batch` and `kubectl auth can-i get pods/log` against the
  pod's kubeconfig. Without `pods/log` a capture still runs but reports no archive size and a
  generic failure reason.
- **The Job runs as root** (uid 0) to read files owned by the runtime user and to restore
  ownership. It therefore requires a namespace that is not Pod Security `restricted`.
  `agent-farm` is labelled `privileged` by `k8s/agent-farm-user.yaml`; namespaces created
  out-of-band, including `agent-farm-staging`, inherit whatever the cluster defaults to.
- **On `local-path`, restore points are node-local and unreplicated.** Each restore point gets
  its own PVC sized by `RESTORE_POINT_SIZE`, provisioned on the node holding the Agent's
  volume. They do not survive loss of that node, and they consume real node disk — the only
  bound is `RESTORE_POINT_MAX_PER_AGENT`, which is per Agent and not per Organization.
- Restore point rows resolve from live Job status when they are read, and a
  `<release>-restore-point-reconciliation` CronJob resolves the ones nobody reads. It runs every
  10 minutes (`restorePoints.reconciliation.schedule`, disable with
  `restorePoints.reconciliation.enabled=false`) under `concurrencyPolicy: Forbid`, and needs the
  same `batch/jobs` and PVC permissions as the API pod because it authenticates with the same
  mounted kubeconfig. Run one pass by hand with `make reconcile-restore-points`, which targets
  whatever `K8S_KUBECONFIG_PATH` and `K8S_NAMESPACE` point at — check both before invoking it
  against a shared cluster.
- **The reconciler deletes storage**, so watch its first few runs in staging before trusting the
  schedule. Each run logs a one-line summary: `claimed`, `resolved`, `replays_attempted`,
  `volumes_missing`, `orphans_deleted`, `orphans_unidentified`, `failed`. A non-zero
  `orphans_unidentified` means resources carrying the component label that match neither route
  below, which the sweep refuses to touch — investigate rather than ignore, because nothing will
  ever reclaim them. A climbing `failed` means rows are being claimed and not resolved, which is
  where to look first if volumes stop being reclaimed.
- **Reclamation identifies a resource by its `agentbarn.io/restore-point-id` label, falling back
  to its name.** The label is not enough on its own: resources created before chart `0.10.0` do
  not carry it. The names are generated by `builders/restore_point.py`
  (`restore-point-<uuid>`, `rp-cap-<uuid>`, `rp-res-<uuid>-<suffix>`), so parsing one back is
  exact rather than a guess. Before deploying `0.10.0` to a cluster that already has restore
  points, `kubectl get pvc,job -l agentbarn.io/component=restore-point -L
  agentbarn.io/restore-point-id` shows what the first sweep will newly be able to act on —
  anything with an empty last column was previously inert and is now reclaimable if no row owns
  it.
- The sweep is deliberately conservative in three further ways, so a stale database or a bad
  listing cannot empty the namespace: a resource younger than
  `RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS` is left alone, deletions are capped at
  `RESTORE_POINT_ORPHAN_DELETE_LIMIT` per run, and a failed or empty PVC listing fails no rows at
  all. A large backlog therefore drains over several runs rather than one.

### Business Action backfill

Ingest records Business Actions only for Tool Calls it completes after the Business Value
release (see [`../features/business-value.md`](../features/business-value.md)). The backfill
classifies the history that already exists. It is operator-run and never scheduled: nothing
calls it from a router, and no CronJob runs it.

- Run it against a deployed release from the API container, which holds the database
  credentials:
  `kubectl -n <namespace> exec deploy/<release> -c api -- python -c "from api.domains.business_value.backfill import main; main()"`.
  Locally, `make backfill-business-actions` runs the same entry point against whatever
  `DB_CONNECTION_URL` points at, so check that value before invoking it.
- It walks completed `terminal` and `exec` Tool Calls in id order, `BACKFILL_BATCH_SIZE`
  (500) per batch.
  - It infers each action's status from the stored result, never from the Tool Call's own
    status.
  - It writes each batch in its own transaction, so an interrupted run keeps the batches it
    finished.
- It is safe to re-run. For each Tool Call it makes the stored rows match the current
  catalogue, keyed on `(tool_call_id, ordinal)`, and it never changes a row's `status`:
  - It inserts rows that are missing.
  - It updates `integration`, `resource`, `verb`, `is_write`, and `outcome_type` (and
    `updated_at`) only on rows whose mapping actually changed.
  - It deletes rows the catalogue no longer produces, for example a path that is now ignored,
    including every row of a Tool Call that now classifies to nothing.
- A re-run with no catalogue change writes nothing and reports `recorded=0 removed=0`.
- Each run logs one summary line: `scanned`, `recorded` (rows inserted or changed), `removed`,
  `failed`. A non-zero `failed` means the classifier raised for those Tool Calls, whose ids are
  logged individually. They are skipped, not retried, and keep their stored rows.
- Classifier code changes that alter how a command is split into invocations can shift
  ordinals. The backfill then deletes and re-inserts those Tool Calls' rows with new ids
  instead of updating them.
