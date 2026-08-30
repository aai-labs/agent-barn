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
make dev-api     # product API on :8000
make dev-ui      # UI on :3000
./run.sh         # full Docker stack (db/redis/api/worker/ui + k3d), including the separately served Ingest app
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

## Staging environment

Staging is a fully separate stack in its own namespace (`agent-farm-staging`), driven off the `staging` branch — not a GitHub Environment (Free plan + private repo can't gate those). `main` remains the k3s testing-ground deploy source. Hosted public production is the Talos cluster via release tags; see [Public cluster (Talos)](#public-cluster-talos). See [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why staging is a namespace.

- **Trigger:** `deploy.yml` runs on pushes to `staging` and `main`, and via `workflow_dispatch`; it resolves `NAMESPACE`/`ENVIRONMENT`/image-tag suffix/hosts/secrets from `github.ref_name`. Dispatching from anything other than `staging` or `main` fails the workflow.
- **Images:** all four images (api, ui, hermes-base, openclaw-base) get a `-staging` tag suffix on staging; staging never pushes `:latest`, since each environment builds its own base images and their installed contents can diverge.
- **Change detection:** `deploy.yml` compares the current commit with the latest successful deploy run for the same branch. A failed deploy does not advance that baseline, so a later fix rebuilds every component changed since the last successful deploy. If no valid baseline can be found, or the workflow is dispatched manually, all four images are built.
- **Secrets/vars:** every per-env value uses a `STAGING_`-prefixed GitHub secret or variable, selected by a `github.ref_name == 'staging' && secrets.STAGING_X || secrets.X` ternary in `deploy.yml`. Shared references (registry, `OPENROUTER_API_KEY`, Google OAuth client, DB user/db names, and the Cloudflare email account/token) are reused as-is. Email follows the standard convention: only `STAGING_SENDER_EMAIL` differs, pointing staging at its own `mail-staging.` sending subdomain.
- **RBAC bootstrap:** `k8s/agent-farm-user.staging.yaml` provisions the `agent-farm-user` ServiceAccount/Role/RoleBinding for `agent-farm-staging` (omitting the cluster-scoped `Namespace` object, since a namespace-scoped kubeconfig can't create one and the namespace is expected to pre-exist). `deploy.sh` applies the prod manifest by default; a staging bring-up points its `kubectl apply` line at the staging manifest instead.
- **Local bring-up:** copy `.env.deploy.spec` to `.env.deploy.staging`, set `NAMESPACE=agent-farm-staging`, the staging hosts, the four `*_IMAGE_TAG=<ver>-staging`, and the same passwords/keys as the `STAGING_*` GitHub secrets (they must match — see the ADR's consequences), then run `ENV_FILE=.env.deploy.staging bash deploy.sh`.
- **Isolation invariant:** the API pod's `K8S_NAMESPACE` env var (from `{{ .Release.Namespace }}` in the API chart) must stay wired, or the staging API would create agent workloads in the prod namespace instead of its own.

## Public cluster (Talos)

Hosted public Agent Barn runs on the dedicated Talos cluster, not on k3s. k3s (`staging` / `main` via `deploy.yml`) stays the AAI Labs testing ground. Public deploys only from a `vX.Y.Z` tag via `../../.github/workflows/deploy-public.yml`. Rationale: [`../adr/2026-08-27-public-cluster-release-tags.md`](../adr/2026-08-27-public-cluster-release-tags.md).

- **Trigger:** pushing a tag matching `v*.*.*`, or `workflow_dispatch` of that tag from `main`. Dispatch can set `skip_build` to re-run helmfile against images already in the registry (no 20-minute rebuild). Helmfile uses the dispatch branch; image tags still come from the release tag.
- **Images:** API and UI are tagged with the git tag (and `:latest` on the **public** registry only). Hermes/OpenClaw keep the versions in their `VERSION` files. Nothing in this workflow writes to `registry.k8s.aai-labs.com`.
- **Registry:** `PUBLIC_REGISTRY_URL` (`registry.agentbarn.dev`). Do not reuse the k3s registry password or R2 bucket.
- **Namespace:** still `agent-farm` so helmfile and `k8s/agent-farm-user.yaml` apply unchanged. This is a different cluster, so it does not collide with k3s.
- **Secrets/vars:** every public-only value is `PUBLIC_`-prefixed. Postgres **user/db names**, `AGENT_DEFAULT_MODEL` / `AGENT_MODEL_ALLOWLIST`, the Cloudflare email account/token, and the Google OAuth client are reused. OpenRouter, Firecrawl, Slack webhook, DB passwords, and signing keys are **not** reused — copy a value into a `PUBLIC_` secret only when that sharing is intentional.
- **Kubeconfig:** `PUBLIC_KUBECONFIG_B64` must reach the Talos API (`https://<cp-1>:6443`). There is no bastion tunnel. `PUBLIC_POD_KUBECONFIG_B64` is what the API pod uses to manage agents; if unset, the workflow falls back to the deploy kubeconfig. Prefer a namespace-scoped kubeconfig for the pod, as on k3s.
- **Storage:** `PUBLIC_STORAGE_CLASS`. Intended value is `rook-ceph-block-main`. Use `local-path` only while Ceph has no OSDs — postgres then dies with the node that holds the volume.
- **Hosts:** `PUBLIC_UI_HOST` is `cloud.agentbarn.dev` (not `app` — that hostname stays on k3s). Product Grafana is `grafana-app.agentbarn.dev`, not cluster `grafana.agentbarn.dev`.
- **RBAC bootstrap:** the deploy kubeconfig is cluster-admin, so the workflow applies `k8s/agent-farm-user.yaml` (creates the namespace) before helmfile.
- **Release command:** from a commit already on `main` that you want public:

```bash
git tag v0.15.0
git push origin v0.15.0
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

Generate new values; do not paste k3s `POSTGRES_*` / signing keys. Encode kubeconfigs with `base64 -w0`.

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

Shared with k3s (already present): `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `GOOGLE_CLOUD_CLIENT_SECRET`, `AAI_CLI_REPO_ACCESS_TOKEN`.

## Versioning and releases

Each deployable chart has independent chart metadata in `Chart.yaml`:

- Chart `version` is the packaging version. Bump it when chart templates or values change, independently of application code.

Rules:

- API and UI image tags are explicit deployment inputs (`API_IMAGE_TAG`, `UI_IMAGE_TAG`), not chart metadata.
- Bump chart versions late, ideally immediately before the PR, to reduce merge conflicts, when chart packaging actually changed.
- The git commit or PR is the product release identifier; there is no shared API/UI release number.
- `../../.github/workflows/deploy.yml` builds API and UI images under moving environment tags and passes those tags into Helm via `API_IMAGE_TAG` and `UI_IMAGE_TAG`: `latest` on `main`, `latest-staging` on `staging`. Branch deploys no longer depend on chart `appVersion` bumps.
- Public hosted deploys (`../../.github/workflows/deploy-public.yml`) pin API/UI to the git tag (`vX.Y.Z`) on `registry.agentbarn.dev`. They never move k3s `latest` tags.
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
- Keep runtime/platform differences explicit when changing Hermes, OpenClaw, Slack, Teams, or Telegram deployment configuration.
- On k3s, use `deploy.yml` rather than manually publishing mutable `latest` tags. Public hosted releases are git tags via `deploy-public.yml`.
