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

## Organization LLM budgets

Budget enforcement is disabled by default. With LiteLLM configured, teams are
still provisioned and keys assigned even when no cap is set. No schema migration
or Agent restart is required. The behavior contract is in
[Costs](../features/costs.md#organization-llm-budgets).

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ORGANIZATION_LLM_BUDGET_USD` | Empty/unset | Each Organization's independent USD allowance; empty removes enforcement. Non-negative finite number; `0` is a zero allowance. |
| `ORGANIZATION_LLM_BUDGET_DURATION` | `30d` | Positive integer followed by `s`, `m`, `h`, or `d`; `30d` is a 30-day interval, not a calendar month. Only applied while an allowance is set. |

Values flow through Helmfile to `organizationLlmBudgetUsd` and
`organizationLlmBudgetDuration` in the API chart. Native and Compose development
read the same variables from `.env`. Set these GitHub Actions repository variables
before deploying the environments that need enforcement:

| Deployment | USD variable | Optional duration variable |
| --- | --- | --- |
| `agentbarn.k8s.aai-labs.com` (`main`) | `ORGANIZATION_LLM_BUDGET_USD` | `ORGANIZATION_LLM_BUDGET_DURATION` |
| `cloud.agentbarn.dev` (public release) | `PUBLIC_ORGANIZATION_LLM_BUDGET_USD` | `PUBLIC_ORGANIZATION_LLM_BUDGET_DURATION` |
| k3s staging | `STAGING_ORGANIZATION_LLM_BUDGET_USD` | `STAGING_ORGANIZATION_LLM_BUDGET_DURATION` |

No dollar amount is hardcoded. Staging does not fall back to the main allowance.
For example, setting the relevant USD variable to `50` gives each Organization
$50 per 30 days. Saving a GitHub variable alone does not update running pods:
redeploy the appropriate workflow. Clearing it and redeploying removes the cap
from existing teams as well as new ones. No hostname-based logic is involved.

On rollout, the API reconciles every existing Organization and Agent key before
becoming ready. The API startup probe allows up to ten minutes for bootstrap and
reconciliation before liveness takes over. Look for
`Organization LiteLLM teams and budgets reconciled` in
the API log. Failure aborts startup and a pod restart retries idempotently;
inspect proxy availability, the Kubernetes master-key Secret, and conflicting
team assignments. Existing Agent pods remain active during this pass, so API
readiness failure is not a spend stop for previously running Agents. For a
controlled cutoff during initial enrollment, stop those Agents before rollout.
Historical pre-enrollment spend remains in reports but is not added to the new
team counter. Verify `/team/info` for a selected Organization UUID and confirm its
keys' `team_id` through the LiteLLM admin interface before relying on enforcement.

For a manual retry with the same environment as the API, run inside its container:

```bash
python -c "from api.domains.organizations.llm import main; main()"
```

The command requires the API database, encryption key, LiteLLM URL, Kubernetes
namespace and master-key Secret access. It exits nonzero on failure. Do not run it
with an empty budget environment against a deployment intended to have a cap:
empty is an explicit instruction to remove the cap. Use the API container's
existing environment. Changing only the amount preserves spend and renewal;
changing duration moves the next renewal, without resetting spend immediately.

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
- **The Worker deploys through CI**, not by hand. `deploy.yml`'s `deploy-worker` job publishes it on merges to `staging`/`main`, but only when `workers/**` changed, and only after the cluster deploy succeeds — the Worker posts into the Communications service, so the cluster must already hold the matching secret. Pull requests run `wrangler deploy --dry-run` through `ci.yml`, which needs no Cloudflare credentials. This requires **`CLOUDFLARE_WORKERS_TOKEN`** (account-owned, scoped to `Workers Scripts: Edit`), deliberately separate from the `Email Sending: Edit` token so one leak cannot both send mail as the domain and replace the Worker receiving it.
- **`EMAIL_INBOUND_SECRET` is written to the Worker and the cluster by the same run**, from one GitHub secret, so the two cannot drift. **Rotating it has a brief window**: the two are updated by consecutive steps, so mail arriving between them bounces `401`. To rotate without that, set the Worker's copy first with `wrangler secret put EMAIL_INBOUND_SECRET --env <env>`, then update the GitHub secret and deploy.
- **Break-glass manual deploy** (a broken pipeline, or first-time bring-up before the token exists): `cd workers/email-inbound && pnpm install && pnpm exec wrangler deploy --env production`. Prefer CI — a hand-deployed Worker can drift from the committed source with nothing detecting it.
- **A routing rule names one specific Worker, and CI cannot repoint it.** When an environment's rule was created against a differently-named Worker — a `--env local` one used for tunnel testing, say — publishing through CI creates the correctly-named Worker but leaves the rule pointing at the old one, so mail keeps going to the stale Worker. Cut over in this order: **let CI publish first, then repoint the rule's destination, and only then delete the old Worker.** Deleting first leaves the rule aimed at nothing and bounces every message for that domain.
- **Delete `--env local` Workers when finished.** They point at a `cloudflared` tunnel that stops existing when the laptop closes, and an account accumulating them is an account where it is easy to point a rule at the wrong one.
- Deploys publish a **new version of one Worker per environment**, not new Workers; Cloudflare retains ~100 versions for `wrangler rollback`. That is why the deploy is path-filtered: unrelated merges would otherwise consume the rollback history.
- **Local k3d testing**: a Worker runs on Cloudflare's edge and cannot reach a local cluster. Either expose the Communications service with a tunnel (`cloudflared tunnel`) and point `INBOUND_URL` at it, or skip the Cloudflare hop entirely and exercise the whole Agent Barn path by posting the Worker's JSON straight at `/communications/v1/webhooks/email/inbound` with the configured bearer token.
- **Agent mail draws on the same account-wide sending quota** as invites, password resets, and lifecycle notifications, across both environments. A chatty Agent can starve real user invites; see the quota note above.
- Relevant limits: 200 routing rules per domain, 200 verified destination addresses per account, 30 domains per zone, 25 MiB inbound message size.

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
| `PUBLIC_FIRECRAWL_API_KEY` | New (this cluster's Firecrawl) |
| `PUBLIC_OPENROUTER_API_KEY` | Prefer a dedicated key so public traffic is not the testing quota |
| `PUBLIC_SLACK_ALERTS_WEBHOOK_URL` | `#alerts` or a public-specific channel |

Shared with k3s (already present): `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_API_TOKEN`, and `GOOGLE_CLOUD_CLIENT_SECRET`.

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
- Required GitHub Actions config: secrets `SLACK_ALERTS_WEBHOOK_URL` (incoming webhook for `#alerts`) and `GRAFANA_ADMIN_PASSWORD`; variable `GRAFANA_HOST` (DNS must resolve for the http01 challenge). The credits metric reuses the existing `OPENROUTER_API_KEY` secret (the API polls `GET /key` for the key's `limit_remaining`); for `OpenRouterCreditsLow` to be meaningful, set a credit limit on that key at openrouter.ai — an unlimited key reports `+Inf`.
- Monitoring verification and its prerequisites live in
  [`testing.md`](testing.md#verification-commands). CI selects
  `.github/workflows/monitoring.yml` for `helm/monitoring/**` changes.
- Agents that were already running before the monitoring deploy are invisible to Prometheus until stopped and started once: the `/metrics` sidecar script and the Service labels the agent scrape config relies on (`agentbarn.io/component`, `agent-name`, `org-name`) only apply when the API rebuilds the agent's resources in the start flow. When only the scrape label is missing (e.g. agents predating the agentfarm→agentbarn rebrand), no restart is needed — patch the Service labels in place, which does not disturb running pods: `kubectl -n NAMESPACE label svc -l agentfarm.io/component=agent agentbarn.io/component=agent --overwrite`.

## Operational safety

- Treat signing-key and encryption-key rotation as migrations: existing tokens or encrypted values depend on the current keys.
- Verify migration and secret-hook behavior when changing API chart startup.
- Keep runtime/platform differences explicit when changing Hermes, OpenClaw, Slack, Teams, Telegram, or Discord deployment configuration.
- The content-free Communications operation journal is retained for
  `COMMUNICATION_JOURNAL_RETENTION_DAYS` days (default `31`, bounded to
  `1`–`3650`). Its supervisor prunes expired entries; changing this window is
  an operational configuration change, not a release-version change.
- On k3s, use `deploy.yml` rather than manually publishing mutable `latest` tags. Public hosted releases are git tags via `deploy-public.yml`.
