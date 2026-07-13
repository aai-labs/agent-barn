# Plan: Staging branch & deployment (AF-149)

## Context

The repo had exactly one environment. Every Helm release in `helmfile.yaml.gotmpl`
was pinned to `namespace: agent-farm`, and `deploy.yml` (a `workflow_dispatch`-only job)
built four images, pushed `<ver>` + `:latest`, then `helmfile sync`ed into that single
namespace with `ENVIRONMENT: production` hardcoded and prod-only secrets/vars.

We want a **staging** environment that:
- has the repo's **default branch = `staging`**,
- deploys via the existing workflow **when dispatched from `staging`**,
- runs as a **fully separate stack with its own DB**, and
- is reachable at its **own hostname**.

**Approach: a separate namespace `agent-farm-staging`,** driven by a `NAMESPACE` env var in
helmfile, plus `STAGING_`-prefixed GitHub secrets/vars selected by a branch check in
`deploy.yml`. A separate namespace is the cheapest correct isolation: Kubernetes short-name
service DNS is namespace-relative, so the hardcoded connection strings (`postgres-app`,
`postgres-litellm`, `litellm:4000`) and fixed secret names (`registry-pull-secret`,
`agent-farm-user-kubeconfig`, `litellm-api-key`) resolve correctly per-namespace and never
collide — **no chart/DNS edits**. It also lets the staging API pod hold a kubeconfig scoped
to `agent-farm-staging`, so it structurally cannot touch prod's agent workloads.

GitHub Environments are **not** usable (Free plan + private repo can't gate them), so
per-environment config lives in `STAGING_`-prefixed secrets/vars chosen at runtime via a
ternary on `github.ref_name`.

### Locked decisions (confirmed with user)

| Topic | Decision |
|---|---|
| Isolation | Separate namespace `agent-farm-staging` |
| Trigger | Manual `workflow_dispatch`, dispatched from `staging` |
| Prod branch | `main` stays the production deploy source |
| Default branch | Flip GitHub default to `staging` |
| Hostnames | UI `agent-farm-staging.k8s.aai-labs.com`, API `api.agent-farm-staging.k8s.aai-labs.com` (hyphens — Let's Encrypt rejects underscores) |
| Image tags | **All four** images (api, ui, openclaw-base, hermes-base) suffixed `-staging`; do **not** push `:latest` from staging (each env builds its own base images, whose installed contents can diverge) |
| `ENVIRONMENT` | `staging` (cosmetic; no app branching keys on it) |
| Email on staging | **Disabled** (no real invite/reset mail from staging) |
| Google OAuth (Gmail) | **Reuse the prod client**; add the staging redirect URI in Google Cloud Console (else leave blank to disable Gmail on staging) |
| First bring-up | **Local `deploy.sh`**, then wire CI |

**Pre-done outside this repo:** the `agent-farm-staging` namespace and a staging kubeconfig
both exist. RBAC (`agent-farm-user` SA/Role/RoleBinding) state is unknown — the first
`deploy.sh` run applies it idempotently.

---

## PART 1 — Code changes in this repo

### A. Chart — API namespace isolation (the linchpin)

`helm/agentfarm-api/templates/deployment.yaml`: add to the container `env:` list

```yaml
- name: K8S_NAMESPACE
  value: {{ .Release.Namespace }}
```

Without this, `Config.k8s_namespace` (`api/core/config.py:33`) falls back to its hardcoded
`"agent-farm"` and the staging pod would create agent Deployments/Services/PVCs/Secrets in
the **prod** namespace (used across `api/domains/agents/service.py`,
`conversations/service.py`, `tool_calls/sync_service.py`, `litellm/client.py`). Correct for
prod too (`agent-farm` → `agent-farm`).

### B. Helmfile — parameterize namespace + pass image tags

`helmfile.yaml.gotmpl`:
1. On **all 5 releases**, `namespace: {{ env "NAMESPACE" | default "agent-farm" }}`.
2. In **all 3 `needs:` blocks**, qualify with the same expr, e.g.
   `- {{ env "NAMESPACE" | default "agent-farm" }}/postgres-app` (helmfile `needs` are
   `<namespace>/<release>`; a templated namespace with un-templated needs breaks resolution).
3. Add `image.tag` set entries to **agentfarm-api** and **agentfarm-ui**:
   `value: {{ env "API_IMAGE_TAG" | default "" | quote }}` (ui → `UI_IMAGE_TAG`). Empty keeps
   the chart's `| default .Chart.AppVersion` fallback, so prod is unchanged. openclaw/hermes
   tags already flow via existing `openclawImage.tag`/`hermesImage.tag` set entries.

### C. Staging namespace bootstrap manifest (RBAC only)

New file `k8s/agent-farm-user.staging.yaml`: the `agent-farm-user` **ServiceAccount + Role +
RoleBinding** for `agent-farm-staging` — **omitting the `Namespace` object** (it already
exists; a namespace-scoped kubeconfig can't GET/create a cluster-scoped Namespace, which
would make `kubectl apply` fail). This is the identity the litellm-key pre-install Job runs as
(`litellm-key-job.yaml:20` hardcodes `serviceAccountName: agent-farm-user`, namespaced to
`.Release.Namespace`). Idempotent.

### D. CI — `.github/workflows/deploy.yml`

1. **New "Resolve environment" step** (after Checkout): branch on `github.ref_name`, write
   non-secret env to `$GITHUB_ENV`, fail on anything else:
   - `staging` → `NAMESPACE=agent-farm-staging ENVIRONMENT=staging IMAGE_SUFFIX=-staging
     PUSH_LATEST=false`, hosts/URL from `vars.STAGING_*`.
   - `main` → `NAMESPACE=agent-farm ENVIRONMENT=production IMAGE_SUFFIX= PUSH_LATEST=true`,
     hosts/URL from `vars.*`.
   - else → `exit 1` (blocks deploys from feature branches).
2. **"Read image versions"**: append `${IMAGE_SUFFIX}` to all four tags.
3. **All four build/push steps**: push `<ver>` (already suffixed); only tag & push `:latest`
   `if [ "${{ env.PUSH_LATEST }}" = "true" ]`.
4. **"Extract primary API host"**: read `${{ env.API_HOST }}` (not `vars.API_HOST`).
5. **"Set up kubeconfig"**: per-env decode —
   `${{ github.ref_name == 'staging' && secrets.STAGING_KUBECONFIG_B64 || secrets.KUBECONFIG_B64 }}`.
6. **"Helmfile sync" `env:` block**: add `NAMESPACE`; switch `ENVIRONMENT`, `WEB_APP_URL`,
   `API_HOST`, `UI_HOST` to resolved `env.*`; per-env secrets via
   `${{ github.ref_name == 'staging' && secrets.STAGING_X || secrets.X }}` for
   `POSTGRES_APP_PASSWORD`, `POSTGRES_LITELLM_PASSWORD`, `LITELLM_MASTER_KEY`,
   `SECRET_SIGNING_KEY`, `SUPER_USER_CREDENTIALS`, `AGENT_TOKEN_ENCRYPTION_KEY`,
   `KUBECONFIG_B64`, `POD_KUBECONFIG_B64`; email via the **inverted** pattern
   `${{ github.ref_name == 'main' && <prodValue> || '' }}` (so staging = empty/disabled, not
   an accidental prod fallback — the `&& || ` idiom falls back to the RHS when the LHS is
   empty). Shared refs (`REGISTRY_*`, `BASTION_SSH_KEY`, `OPENROUTER_API_KEY`, `STORAGE_CLASS`,
   `AGENT_DEFAULT_MODEL`, `AGENT_MODEL_ALLOWLIST`, `GOOGLE_CLOUD_CLIENT_ID/SECRET`, DB
   user/db names) left untouched.

### E. `deploy.sh`, env spec & docs

- `deploy.sh`: no code change — for the staging run you manually point its
  `kubectl apply -f k8s/agent-farm-user.yaml` at `k8s/agent-farm-user.staging.yaml`. It
  already `set -a` exports the env file, so `NAMESPACE` + the four `*_IMAGE_TAG`s flow into
  helmfile.
- `.env.deploy.spec`: added `NAMESPACE` + commented staging guidance (the `-staging` tag
  convention, the user-manifest line).
- `CLAUDE.md`: added a "Staging environment" section + the `STAGING_` secrets/vars list.

### Files changed / created
- `helm/agentfarm-api/templates/deployment.yaml` — add `K8S_NAMESPACE` (§A)
- `helmfile.yaml.gotmpl` — namespace + needs templating, api/ui `image.tag` (§B)
- `k8s/agent-farm-user.staging.yaml` — **new**, RBAC-only (§C)
- `.github/workflows/deploy.yml` — resolve/guard, suffix all 4 tags, `:latest` gate, per-env
  kubeconfig decode, env-selected values, ternary/inverted secrets (§D)
- `.env.deploy.spec`, `CLAUDE.md` — staging docs (§E). `.env.deploy.staging` is created
  locally and **gitignored** (never committed).

No changes to postgres/litellm/ui templates, connection strings, or the litellm-key job —
namespace-relative resolution handles them.

---

## PART 2 — External setup checklist (NOT in this codebase — done by the operator)

### 2.1 GitHub → Settings → Secrets and variables → Actions → **Variables**
| Variable | Value |
|---|---|
| `STAGING_API_HOST` | `api.agent-farm-staging.k8s.aai-labs.com` |
| `STAGING_UI_HOST` | `agent-farm-staging.k8s.aai-labs.com` |
| `STAGING_WEB_APP_URL` | `https://agent-farm-staging.k8s.aai-labs.com` |

*Reused as-is (no staging copy):* `REGISTRY_URL`, `REGISTRY_USERNAME`, `POSTGRES_APP_USER`,
`POSTGRES_APP_DB`, `POSTGRES_LITELLM_USER`, `POSTGRES_LITELLM_DB`, `AGENT_DEFAULT_MODEL`,
`AGENT_MODEL_ALLOWLIST`, `STORAGE_CLASS`, `GOOGLE_CLOUD_CLIENT_ID`. (`EMAIL_SMTP_SERVER`,
`EMAIL_FROM_ADDRESS` are ignored on staging — email disabled.)

### 2.2 GitHub → **Secrets** (generate fresh, distinct from prod)
| Secret | How to produce |
|---|---|
| `STAGING_POSTGRES_APP_PASSWORD` | `openssl rand -hex 24` |
| `STAGING_POSTGRES_LITELLM_PASSWORD` | `openssl rand -hex 24` |
| `STAGING_LITELLM_MASTER_KEY` | `echo "sk-$(openssl rand -hex 24)"` |
| `STAGING_SECRET_SIGNING_KEY` | `openssl rand -hex 32` |
| `STAGING_SUPER_USER_CREDENTIALS` | `admin@example.com:<password>` |
| `STAGING_AGENT_TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `STAGING_KUBECONFIG_B64` | `base64 -w0 <staging-kubeconfig>` (CI runner → helmfile sync) |
| `STAGING_POD_KUBECONFIG_B64` | `base64 -w0 <staging-kubeconfig>` (baked into the API pod; **same value is fine**) |

> ⚠️ Staging DB/LiteLLM passwords + keys are set **once at first bring-up** and baked into the
> namespace's secrets + Postgres data dir. Use the **same values** in `.env.deploy.staging`
> and in these GitHub secrets, or a later CI sync writes a new app-DB secret that no longer
> matches the password already initialized in the Postgres PVC (auth failures).

*Reused as-is:* `REGISTRY_PASSWORD`, `AAI_CLI_REPO_ACCESS_TOKEN`, `BASTION_SSH_KEY`,
`OPENROUTER_API_KEY`, `GOOGLE_CLOUD_CLIENT_SECRET`. `EMAIL_SERVER_CREDENTIAL` is used only on
`main`.

### 2.3 GitHub → repo settings
- Create branch `staging` from `main`, push it.
- `gh repo edit aai-labs/agent-farm --default-branch staging` (or Settings → General).
  ⚠️ Changes new-PR base + fresh `git clone` checkout for the whole team — coordinate first.

### 2.4 Cluster (kubectl, one-time)
- **RBAC (state unknown):** ensure `agent-farm-user` SA/Role/RoleBinding exist in
  `agent-farm-staging`. The first `deploy.sh` run applies `k8s/agent-farm-user.staging.yaml`
  for you. Pre-check: `kubectl -n agent-farm-staging get sa agent-farm-user`. Manual:
  `kubectl apply -f k8s/agent-farm-user.staging.yaml`.
- The staging kubeconfig must be **namespace-admin** in `agent-farm-staging` (create
  Deployments/StatefulSets/Services/PVCs/Secrets/Ingresses/Jobs + the SA/Role/RoleBinding).

### 2.5 DNS & TLS
- **DNS:** the `*.k8s.aai-labs.com` wildcard already covers both new hosts — nothing to do
  (confirm the wildcard; else add A/CNAME for `agent-farm-staging` + `api.agent-farm-staging`).
- **TLS:** cert-manager + `letsencrypt-http01` issues on-demand per host — nothing to do
  beyond the hosts resolving publicly.

### 2.6 Google Cloud Console (only if Gmail on staging is wanted)
- Add `https://agent-farm-staging.k8s.aai-labs.com/api/v1/integrations/google/callback` to the
  existing OAuth "Web application" client's **Authorized redirect URIs**. Otherwise leave
  `GOOGLE_CLOUD_CLIENT_ID/SECRET` blank for staging.

### 2.7 Shared-resource acknowledgements
- Staging shares the **OpenRouter** account (billing) and the **container registry** (`aailabs/`
  — now with `*-staging` tags). Acceptable for staging; flag if separate OpenRouter billing is
  wanted.

---

## First bring-up runbook (local `deploy.sh`, then CI)

1. **Build & push the four `*-staging` images** (deploy.sh does **not** build). Either a CI run
   from `staging` (builds + pushes + syncs), or build manually
   (`docker build -t registry.k8s.aai-labs.com/aailabs/agentfarm-<img>:<ver>-staging …` for
   api/ui/hermes-base/openclaw-base; base builds need the `gh_token` secret), then push.
2. **`.env.deploy.staging`** (copy `.env.deploy.spec`, gitignored): `NAMESPACE=agent-farm-staging`,
   `ENVIRONMENT=staging`, the three staging hosts/URL, the four `*_IMAGE_TAG=<ver>-staging`, the
   **same** staging passwords/keys as the GitHub secrets, `KUBECONFIG=<staging kubeconfig>`,
   `POD_KUBECONFIG_B64=$(base64 -w0 <staging kubeconfig>)`, shared `REGISTRY_*`,
   `OPENROUTER_API_KEY`, `STORAGE_CLASS=local-path`, (optional) Google client.
3. **Point deploy.sh at the staging user-manifest** (edit its `kubectl apply` line →
   `k8s/agent-farm-user.staging.yaml`).
4. **Run:** `ENV_FILE=.env.deploy.staging bash deploy.sh`. Applies RBAC, then `helmfile sync
   --wait` creates both Postgres, litellm, api, ui, ingresses + all in-namespace secrets in
   `agent-farm-staging`.
5. **Wire CI:** add the GitHub vars/secrets (§2.1–2.2), push `staging`, flip the default branch
   (§2.3), dispatch `deploy.yml` from `staging`.

---

## Verification (done for the render steps)

1. **Render (no cluster):** `helmfile -f helmfile.yaml.gotmpl template` with
   `NAMESPACE=agent-farm-staging` + the four `*_IMAGE_TAG=<ver>-staging` → **✅ all 23 objects
   `namespace: agent-farm-staging`**, api/ui + the pod's `OPENCLAW_IMAGE`/`HERMES_IMAGE` end in
   `-staging`, `K8S_NAMESPACE=agent-farm-staging`. Re-run with no `NAMESPACE`/suffix → **✅ back
   to `agent-farm`**, api/ui fall back to `AppVersion` (0.29.0 / 0.26.1), base images to
   `latest`, `K8S_NAMESPACE=agent-farm` (prod unchanged).
2. **Local k3s dry run** (optional): sync `NAMESPACE=agent-farm-staging` into local k3s.
3. **First bring-up:** runbook → `kubectl get all -n agent-farm-staging` shows the full stack.
4. **Reachability:** `curl https://api.agent-farm-staging.k8s.aai-labs.com/api/v1/health` healthy;
   UI host loads over TLS.
5. **Isolation proof:** create a test agent on staging → its pod is in `agent-farm-staging`, not
   `agent-farm`.
6. **Prod untouched:** `kubectl get all -n agent-farm` unchanged; prod images still unsuffixed; a
   dispatch from `main` still targets `agent-farm` + pushes `:latest`.

---

## Implementation status

**Code (Part 1): DONE** — all edits applied and verified via `helmfile template` for both
staging and prod (verification step 1 ✅). Files: `helm/agentfarm-api/templates/deployment.yaml`,
`helmfile.yaml.gotmpl`, `k8s/agent-farm-user.staging.yaml` (new), `.github/workflows/deploy.yml`,
`.env.deploy.spec`, `CLAUDE.md`.

**Operator (Part 2 + runbook): PENDING** — GitHub vars/secrets, default-branch flip, staging
kubeconfig → `STAGING_*_KUBECONFIG_B64`, optional Google redirect URI, and the first `deploy.sh`
bring-up.

## Open items / risks
- **Secret/password consistency** between `.env.deploy.staging` and the GitHub `STAGING_*`
  secrets (see ⚠️ §2.2) — mismatches surface as Postgres/LiteLLM auth errors on a later sync.
- **Default-branch flip** affects the whole team (PR base, fresh clones) — coordinate.
- **Staging kubeconfig scope** — confirm it's namespace-admin; if not, one broader apply is
  needed for the RBAC.
- Staging **shares OpenRouter billing + the registry** with prod — acceptable for staging.
