# Public Agent Barn deploys from release tags to the Talos cluster

Status: Accepted
Date: 2026-08-27

AAI Labs keeps the existing k3s cluster (`deploy.yml` on `staging` / `main`) as a testing ground for work that is not yet a public release. Hosted public Agent Barn runs on the dedicated Talos cluster and deploys only from a `vX.Y.Z` git tag via `.github/workflows/deploy-public.yml`.

## Considered alternatives

- **Deploy public from `main` like k3s.** Rejected: every merge would ship to paying users. k3s stays the place where unfinished work can land under moving `latest` tags.
- **Reuse `deploy.yml` with a third branch.** Rejected: the public cluster has a different registry, kubeconfig, storage class, ingress hosts, and secrets. A separate workflow keeps the k3s path unchanged.
- **GitHub Environments for gating.** Same constraint as [`2026-07-13-staging-environment-namespace-isolation.md`](2026-07-13-staging-environment-namespace-isolation.md): this private repo cannot rely on Environment protection rules. Public config uses a `PUBLIC_` prefix, matching the `STAGING_` pattern.
- **Push public images to `registry.k8s.aai-labs.com`.** Rejected: the public cluster would depend on the testing cluster's registry. Images go to `registry.agentbarn.dev`.
- **A second cluster for staging.** Not this decision. Staging remains a namespace on k3s. The second cluster is public production, not a staging clone.

## Consequences

- `git push origin vX.Y.Z` (or a manual dispatch of that tag) is the public release. API/UI images are pinned to the tag; Hermes/OpenClaw keep their `VERSION` files. k3s continues to use `latest` / `latest-staging`.
- Per-cluster secrets (`PUBLIC_KUBECONFIG_B64`, DB passwords, signing keys, registry password) must not be copied from k3s. Shared references stay the Cloudflare email account/token and the Google OAuth client (add the public callback URL on cutover if it is not already `app.agentbarn.dev`).
- Helmfile still deploys into namespace `agent-farm` so charts and `k8s/agent-farm-user.yaml` stay as they are. Sandbox namespaces `agent-barn-prod` / `agent-barn-staging` on Talos are not yet the API's agent landing zone; that isolation split is a follow-up.
- Product Grafana on Talos uses `PUBLIC_GRAFANA_HOST` (not `grafana.agentbarn.dev`, which is the cluster kube-prometheus-stack).
- `app.agentbarn.dev` stays on k3s until DNS is pointed at the Talos Traefik VIP. Importing that record is the cutover, not the first workflow merge.
- The 2026-07-13 ADR's rejection of a second cluster applied to staging-vs-prod on k3s. It does not cover this public production cluster.
