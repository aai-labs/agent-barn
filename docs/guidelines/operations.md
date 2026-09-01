# Development and operations

> **Naming note:** the product rebranded from Agent Farm to Agent Barn. Code and deployment identifiers were migrated in that rebrand (`agentbarn_*` metrics, `agentbarn.io` labels, `agentbarn-*` charts/releases/images). Only the Kubernetes namespaces deliberately keep the old name — `agent-farm`, `agent-farm-staging`, and their `<namespace>-user` ServiceAccounts — because renaming them would strand running workloads; treat those as stable identifiers, not branding. Rationale and layer-by-layer blast radius: [`../adr/2026-08-22-agent-barn-rebrand-with-frozen-namespaces.md`](../adr/2026-08-22-agent-barn-rebrand-with-frozen-namespaces.md).

## Install dependencies

From the repository root:

```bash
cd api && uv sync
cd ../ui && pnpm install
```

API configuration is read from the repository root `.env`; tests may use `.env.spec`.

## Local development

```bash
make db-up       # PostgreSQL only
make dev-api     # product API on :8000 plus Ingest :8001 and Communications :8002
make dev-ui      # UI on :3000
./run.sh         # full Docker stack (db/redis/api/worker/ui/communications + k3d), including the separately served Ingest app
./stop.sh        # stop it; ./stop.sh --clean also deletes the k3d cluster
```

Use `make db-down`, `make db-logs`, and `make db-restart` for database lifecycle. Prefer `./run.sh`/`./stop.sh` for the full stack and repository Make targets for individual services over ad hoc equivalents.

## Database migrations

```bash
make migrate
make merge-heads
make rollback
make makemigrations
```

Schema changes require a migration under `../../api/migrations/versions/`. Review generated migrations before applying them. Production deployment runs Alembic through the API chart migration hook described in `../architecture/runtime-and-deployment.md`.

## Checks and tests

Testing and verification commands live in `testing.md`. Run the smallest complete set for the touched area before widening to full suites.

## Deployment shape

The deployable services have independent Helm charts. `../../helmfile.yaml.gotmpl` controls release ordering, and `../../.github/workflows/deploy.yml` builds images and applies Helmfile. Read `../architecture/runtime-and-deployment.md` before changing runtime images, agent Kubernetes resources, chart wiring, migrations, or deployment order.

LiteLLM uses a non-overlapping rolling update (`maxSurge: 0`, `maxUnavailable: 1`): the namespace quota cannot accommodate its old and replacement 2Gi pods at once. Upgrades briefly interrupt the proxy while Kubernetes replaces the pod; do not restore the default surge behavior unless the quota is increased first.

## Transactional email

Invites, password resets, and agent lifecycle notifications send through **Cloudflare Email Sending** (`POST https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send`, Bearer token). `../../api/infrastructure/email/client.py` is the only place that talks to the provider; `EmailService` above it is transport-agnostic.

- **`CLOUDFLARE_ACCOUNT_ID`** and **`CLOUDFLARE_API_TOKEN`** are GitHub secrets; **`SENDER_EMAIL`** is a GitHub variable. All three flow through `helmfile.yaml.gotmpl` into the API chart's Secret. Unset leaves delivery disabled: sends are logged and no-op rather than raising.
- The API token MUST carry the **Email Sending: Edit** permission on the account in `CLOUDFLARE_ACCOUNT_ID`.
- `SENDER_EMAIL`'s domain MUST be onboarded and **Verified** for Email Sending in that account, or Cloudflare rejects every send with `550`-class errors. Sending domains are added in the Cloudflare dashboard (**Email → Email Sending**), never in code, and verification can take up to 24 hours.
- **Each environment sends from its own `mail.`-style subdomain**, never the root domain — production `noreply@mail.agentbarn.dev`, staging `noreply@mail-staging.agentbarn.dev`. Sending reputation is scored per-domain, so this keeps a damaged reputation away from the root domain that serves the website and logins, and away from other environments.
- **`SENDER_EMAIL` is the only per-environment value.** `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are shared references reused across both environments, because one `Email Sending: Edit` token covers every verified domain on the account. Consequence: rotating that token takes both environments down at once. A token cannot be scoped to a single sending domain, so per-environment tokens would buy revocation independence but not access isolation.
- **The daily sending quota is per Cloudflare account, not per domain** — currently 200/day, shared by staging and production. Fine for manual smoke tests; a staging load test or send loop can starve real invites.
- Message size is capped at 5 MiB including attachments. The inline barn logo is sent as a base64 attachment with `disposition: "inline"` and a snake_case `content_id` matching the `cid:` reference in the MJML templates — `contentId` is the Workers binding's spelling and is not accepted by the REST API.

## Per-Agent email addresses

Agents reachable by email get their own address on a dedicated subdomain, receive mail through a Cloudflare Email Worker, and reply through the same Email Sending path as transactional mail. Rationale for the Worker: [`../adr/2026-08-31-cloudflare-worker-for-inbound-email.md`](../adr/2026-08-31-cloudflare-worker-for-inbound-email.md).

- **`AGENT_EMAIL_DOMAIN`** (GitHub variable, `STAGING_` variant) and **`EMAIL_INBOUND_SECRET`** (GitHub secret, `STAGING_` variant) flow through `helmfile.yaml.gotmpl` into the API chart's Secret. Unset leaves the Email platform refusing new Communication Connections; nothing else changes. Both are read by the **Communications deployment** as well as the API — it mounts the same Secret with `envFrom`, so no separate wiring exists.
- Unlike the shared `CLOUDFLARE_API_TOKEN`, `EMAIL_INBOUND_SECRET` is **per-environment**: it is the only credential guarding mail injection, so a staging leak must not reach production. Generate with `openssl rand -hex 32`.
- **The subdomain must be onboarded twice** in the Cloudflare dashboard — once under **Email → Email Routing** (inbound MX) and once under **Email → Email Sending** (the `From` address). They are separate flows with separate DKIM selectors (`cf2024-1._domainkey` and `cf-bounce._domainkey`). Sending verification can take up to 24 hours, and until it is Verified every agent reply fails with a `550`-class error.
- **One routing rule serves every agent.** Email Routing supports RFC 5233 subaddressing, so a single custom-address rule for `agent@agents.agentbarn.dev` → Worker matches `agent+<slug>-<token>@agents.agentbarn.dev` and preserves the `+tag` in `message.to`. No Cloudflare API call happens when an Agent is created. Catch-all is zone-apex only and cannot be used on a subdomain; making the subdomain its own zone is Enterprise-only.
- **Deploy the Worker** from `workers/email-inbound/`: `pnpm install`, then `wrangler secret put EMAIL_INBOUND_SECRET --env production` (matching the cluster value), then `wrangler deploy --env production`. This is manual and outside the Helm/Actions flow, so **a Worker change is not deployed by merging** — the running Worker can drift from the committed source.
- **Local k3d testing**: a Worker runs on Cloudflare's edge and cannot reach a local cluster. Either expose the Communications service with a tunnel (`cloudflared tunnel`) and point `INBOUND_URL` at it, or skip the Cloudflare hop entirely and exercise the whole Agent Barn path by posting the Worker's JSON straight at `/communications/v1/webhooks/email/inbound` with the configured bearer token.
- **Agent mail draws on the same account-wide sending quota** as invites, password resets, and lifecycle notifications, across both environments. A chatty Agent can starve real user invites; see the quota note above.
- Relevant limits: 200 routing rules per domain, 200 verified destination addresses per account, 30 domains per zone, 25 MiB inbound message size.

## Staging environment

Staging is a fully separate stack in its own namespace (`agent-farm-staging`), driven off the `staging` branch — not a GitHub Environment (Free plan + private repo can't gate those). `main` remains the production deploy source. See [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why.

- **Trigger:** `deploy.yml` runs on pushes to `staging` and `main`, and via `workflow_dispatch`; it resolves `NAMESPACE`/`ENVIRONMENT`/image-tag suffix/hosts/secrets from `github.ref_name`. Dispatching from anything other than `staging` or `main` fails the workflow.
- **Images:** all four images (api, ui, hermes-base, openclaw-base) get a `-staging` tag suffix on staging; staging never pushes `:latest`, since each environment builds its own base images and their installed contents can diverge.
- **Change detection:** `deploy.yml` compares the current commit with the latest successful deploy run for the same branch. A failed deploy does not advance that baseline, so a later fix rebuilds every component changed since the last successful deploy. If no valid baseline can be found, or the workflow is dispatched manually, all four images are built.
- **Secrets/vars:** every per-env value uses a `STAGING_`-prefixed GitHub secret or variable, selected by a `github.ref_name == 'staging' && secrets.STAGING_X || secrets.X` ternary in `deploy.yml`. Shared references (registry, `OPENROUTER_API_KEY`, Google OAuth client, DB user/db names, and the Cloudflare email account/token) are reused as-is. Email follows the standard convention: only `STAGING_SENDER_EMAIL` differs, pointing staging at its own `mail-staging.` sending subdomain.
- **RBAC bootstrap:** `k8s/agent-farm-user.staging.yaml` provisions the `agent-farm-user` ServiceAccount/Role/RoleBinding for `agent-farm-staging` (omitting the cluster-scoped `Namespace` object, since a namespace-scoped kubeconfig can't create one and the namespace is expected to pre-exist). `deploy.sh` applies the prod manifest by default; a staging bring-up points its `kubectl apply` line at the staging manifest instead.
- **Local bring-up:** copy `.env.deploy.spec` to `.env.deploy.staging`, set `NAMESPACE=agent-farm-staging`, the staging hosts, the four `*_IMAGE_TAG=<ver>-staging`, and the same passwords/keys as the `STAGING_*` GitHub secrets (they must match — see the ADR's consequences), then run `ENV_FILE=.env.deploy.staging bash deploy.sh`.
- **Isolation invariant:** the API pod's `K8S_NAMESPACE` env var (from `{{ .Release.Namespace }}` in the API chart) must stay wired, or the staging API would create agent workloads in the prod namespace instead of its own.

## Versioning and releases

Each deployable chart has independent chart metadata in `Chart.yaml`:

- Chart `version` is the packaging version. Bump it when chart templates or values change, independently of application code.

Rules:

- API and UI image tags are explicit deployment inputs (`API_IMAGE_TAG`, `UI_IMAGE_TAG`), not chart metadata.
- Bump chart versions late, ideally immediately before the PR, to reduce merge conflicts, when chart packaging actually changed.
- The git commit or PR is the product release identifier; there is no shared API/UI release number.
- `../../.github/workflows/deploy.yml` builds API and UI images under moving environment tags and passes those tags into Helm via `API_IMAGE_TAG` and `UI_IMAGE_TAG`: `latest` on `main`, `latest-staging` on `staging`. Branch deploys no longer depend on chart `appVersion` bumps.
- Manual/bundled release flows also pass explicit API/UI tags rather than reading them from chart metadata.
- LiteLLM, PostgreSQL, and monitoring charts run upstream images; bump only chart `version` when their chart templates change.

Documentation-only changes do not change a service image and do not require a service image-tag change.

## Monitoring stack

`../../helm/monitoring/` (plain namespace-scoped Prometheus + Grafana + Alertmanager) deploys with the regular Helmfile sync. Operational notes:

- Everything the chart renders is namespaced and it creates no RBAC objects at all (the tenant deployer may not create Roles/RoleBindings). Prometheus and kube-state-metrics run under the tenant deploy SA (`<namespace>-user`, set per environment by helmfile), which already has namespaced read; Grafana is the only ingress-exposed pod and runs without a ServiceAccount token. This is what makes the stack deployable on the shared cluster by the namespace-scoped deployer, staging branch included. Note the dashboards ConfigMap is deliberately not labeled `grafana_dashboard` — the cluster's central Grafana imports that label from every namespace.
- Required GitHub Actions config: secrets `SLACK_ALERTS_WEBHOOK_URL` (incoming webhook for `#alerts`) and `GRAFANA_ADMIN_PASSWORD`; variable `GRAFANA_HOST` (DNS must resolve for the http01 challenge). The credits metric reuses the existing `OPENROUTER_API_KEY` secret (the API polls `GET /key` for the key's `limit_remaining`); for `OpenRouterCreditsLow` to be meaningful, set a credit limit on that key at openrouter.ai — an unlimited key reports `+Inf`.
- The pinned prometheus and grafana chart dependencies are rebuilt locally with `helm dependency build helm/monitoring` (`Chart.lock` is committed, the fetched `charts/*.tgz` is gitignored).
- `make check-monitoring` unit-tests the alert rules with promtool and parse-checks every dashboard panel query; run it after touching the alert rules in `helm/monitoring/values.yaml` or the dashboards (needs helm, docker, and the chart dependency built). CI runs it automatically on `helm/monitoring/**` changes (`.github/workflows/monitoring.yml`).
- Agents that were already running before the monitoring deploy are invisible to Prometheus until stopped and started once: the `/metrics` sidecar script and the Service labels the agent scrape config relies on (`agentbarn.io/component`, `agent-name`, `org-name`) only apply when the API rebuilds the agent's resources in the start flow. When only the scrape label is missing (e.g. agents predating the agentfarm→agentbarn rebrand), no restart is needed — patch the Service labels in place, which does not disturb running pods: `kubectl -n <namespace> label svc -l agentfarm.io/component=agent agentbarn.io/component=agent --overwrite`.

## Operational safety

- Treat signing-key and encryption-key rotation as migrations: existing tokens or encrypted values depend on the current keys.
- Verify migration and secret-hook behavior when changing API chart startup.
- Keep runtime/platform differences explicit when changing Hermes, OpenClaw, Slack, Telegram, or Discord deployment configuration.
- Use the existing deployment workflow rather than manually publishing mutable production tags.
