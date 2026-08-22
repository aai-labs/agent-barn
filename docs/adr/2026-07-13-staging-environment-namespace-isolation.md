# Staging environment uses a separate namespace, not GitHub Environments

Status: Accepted
Date: 2026-07-13
Origin: [AF-149](https://aai-labs.atlassian.net/browse/AF-149)

Agent Farm gained a staging environment isolated by Kubernetes namespace (`agent-farm-staging`) rather than by a separate cluster or a GitHub Environment. `helmfile.yaml.gotmpl` reads `NAMESPACE` (default `agent-farm`) and `.github/workflows/deploy.yml` resolves it, plus `ENVIRONMENT`, an image-tag suffix, and every per-env secret/var, from `github.ref_name`: `staging` deploys `agent-farm-staging` with `-staging`-suffixed images and no `:latest` push; `main` deploys `agent-farm` unchanged. Any other ref fails the workflow.

## Considered alternatives

- **GitHub Environments** for per-environment secrets/vars and protection rules. Rejected: the GitHub Free plan on a private repo cannot gate Environments, so this would add configuration without the deployment gate it exists to provide. Per-environment config instead lives in `STAGING_`-prefixed secrets/vars selected by a `github.ref_name` ternary in the workflow.
- **A second cluster.** Rejected as unnecessary cost/operational overhead: Kubernetes short-name service DNS is namespace-relative, so the existing hardcoded connection strings (`postgres-app`, `postgres-litellm`, `litellm:4000`) and fixed secret/SA names resolve correctly per-namespace without chart or DNS edits.

## Consequences

- `api/core/config.py`'s `K8S_NAMESPACE` must be threaded into the API pod's env (`{{ .Release.Namespace }}` in `helm/agentbarn-api/templates/deployment.yaml`); without it the staging API pod would create agent Deployments/Services/PVCs/Secrets in the prod namespace instead of its own, since that setting otherwise falls back to a hardcoded `"agent-farm"`. This also gives the staging API pod a kubeconfig scoped to `agent-farm-staging`, so it structurally cannot touch prod's agent workloads.
- Every `helmfile.yaml.gotmpl` release's `namespace:` and every `needs:` reference must stay templated on the same `NAMESPACE` expression (helmfile's `needs` are `<namespace>/<release>` — an untemplated `needs` against a templated namespace breaks release ordering).
- Staging shares the OpenRouter account (billing) and the container registry with prod, distinguished only by `-staging` image tags. Accepted as an acceptable staging-scope tradeoff, not a security boundary.
- Staging DB/LiteLLM passwords and keys are set once at first bring-up and baked into the namespace's Postgres data dir; the local `.env.deploy.staging` values and the `STAGING_*` GitHub secrets must stay in sync or a later CI sync writes a secret that no longer matches the already-initialized password (auth failures).
- Flipping the repository's default branch to `staging` (so a plain `git clone` lands on staging) affects every contributor's fresh checkout and new-PR base branch; `main` remains the production deploy source regardless of default-branch.
- See [`../guidelines/operations.md`](../guidelines/operations.md) for the operator runbook (required secrets/vars, first bring-up) and [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md) for how this fits the deploy workflow.
