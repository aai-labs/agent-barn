# Security Policy

## Reporting a vulnerability

**Do not open a public issue, Discussion, or Discord message for a security
vulnerability.**

Use either channel:

- **Email [tadas@aai-labs.com](mailto:tadas@aai-labs.com)**
- **[GitHub private vulnerability reporting](https://github.com/aai-labs/agent-barn/security/advisories/new)**, which opens a private thread visible only to you and the maintainers

Both reach the same people. Use email if you would rather not create a GitHub
account or your disclosure process requires a mailbox.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce, or a proof of concept
- The affected commit or image tag, and the deployment method if relevant
- Any suggested mitigation

## What happens next

| Stage | Timeframe |
|---|---|
| Acknowledgement that we received the report | 3 business days |
| Initial assessment and severity triage | 5 business days |
| Status update, then updates at least every 7 days | Ongoing |
| Fix released and advisory published | Depends on severity and complexity |

We aim to release a fix and publish an advisory within 90 days of the report. If
we need longer we will tell you why and agree a revised date with you. If we go
quiet for more than 14 days, chase us; that is a failure on our side.

We credit reporters in the advisory and release notes unless you ask us not to.
We do not currently run a paid bug bounty.

## Scope

In scope:

- The control plane: the API, its Dramatiq worker, the ingest app, and the
  Communications gateway
- The web UI
- The Helm charts, Helmfile, and cluster RBAC manifests in this repository
- The agent runtime packaging we publish: base images, start scripts, health
  and metrics endpoints, and telemetry plugins delivered through runtime
  configuration
- The bundled agent templates and skill documentation, including prompt-level
  issues that let an agent escape the policy it is given

Out of scope:

- Findings that require an already-compromised cluster, node, or admin account
- Vulnerabilities in the upstream agent runtimes (Hermes, OpenClaw) or in the
  third-party images we deploy (LiteLLM, Firecrawl, PostgreSQL, Redis,
  Prometheus, Grafana) with no Agent Barn-specific exploit path. Report those
  upstream; tell us if we need to bump a pin
- Vulnerabilities in third-party dependencies with no Agent Barn-specific
  exploit path, same handling
- Model provider behaviour, including OpenRouter and the models routed through
  it. Report those to the provider
- Denial of service through resource exhaustion by an authenticated operator,
  who can already do this by design
- Missing hardening that is documented as the operator's responsibility, such
  as network policy or database encryption at rest
- Social engineering, physical attacks, or anything requiring access to AAI
  Labs staff accounts

If you are not sure whether something is in scope, report it. We would rather
triage an out-of-scope report than miss an in-scope one.

## Supported versions

Public releases use a `vX.Y.Z` git tag that identifies the API and UI deployment
bundle. Helm charts and the Hermes and OpenClaw runtime images retain independent
versions.

| What | Supported |
|---|---|
| Current `main` | Yes; this is the development head |
| Latest published `vX.Y.Z` release | Yes |
| Older releases or image tags | No; upgrade to a supported version |

Before 1.0, expect the supported window to be short. Track `main` and stay
current.

## Operator responsibilities

Agent Barn runs on your infrastructure, so parts of the security posture are
yours:

- Model provider API keys and tool credentials are stored by you, encrypted at
  rest with keys you generate. `SECRET_SIGNING_KEY` and
  `AGENT_TOKEN_ENCRYPTION_KEY` are the roots of that trust: keep them out of
  version control and treat rotation as a migration, since existing tokens and
  encrypted values depend on the current keys
- The API, UI, and Communications provider-webhook ingress are internet-facing
  by design, with TLS from your cert-manager issuer. The Communications runtime
  endpoints and Ingest stay internal. Put your own network controls in front of
  public routes if that is not what you want, and set a real Grafana admin
  password if you deploy the monitoring chart, whose Grafana is also
  ingress-exposed
- Model traffic leaves your network. Agents call the LiteLLM proxy in your
  namespace, which forwards to OpenRouter. Scope that key and set a credit limit
  on it
- Database encryption at rest, network policy, and node hardening are your
  cluster's concern
- Initial bootstrap credentials may need permission to create the namespace and
  RBAC prerequisites. Give routine deploys only the permissions they need, and
  use a separate namespace-scoped identity for the API pod; it creates agent
  workloads only in its own namespace
- Agents act with the permissions of the credentials you give them. Scope those
  credentials as narrowly as the task allows, and use the per-agent channel
  allowlists and DM policies rather than relying on the prompt alone

[`docs/architecture/runtime-and-deployment.md`](docs/architecture/runtime-and-deployment.md)
and [`docs/guidelines/operations.md`](docs/guidelines/operations.md) cover each of
these, and the
[self-hosting guide](https://agentbarn.dev/guides/self-hosting) walks through a
deployment end to end.
