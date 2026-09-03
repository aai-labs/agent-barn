# Agent pods never hold provider credentials

Status: Proposed
Date: 2026-09-02

Agent pods stop receiving real provider credentials. A credential gateway holds the encrypted credential and either substitutes the real authorization on a forwarded request (`gateway_proxy`) or mints a short-lived upstream token for the pod (`token_broker`). Agent pods hold only a revocable gateway token, and NetworkPolicy confines their egress to the gateway, LiteLLM, and DNS.

## Context

Today `start_agent` decrypts Agent Secrets and writes real provider credentials into the pod. aai-cli providers land in Secret environment and in `aai-secrets.enc.json` on the PVC. Google Workspace lands as `GOG_CLIENT_JSON` plus `GOG_TOKEN_JSON` — an OAuth client secret and a long-lived refresh token.

Hermes and OpenClaw are coding agents that run arbitrary shell. Any credential materialized in the pod is readable by the agent and by anything that successfully prompt-injects it. The refresh token is the worst case: it is a renewable grant, not a single credential, so exfiltration grants durable access that outlives the pod.

Communications already establishes the boundary we want: runtimes never receive provider tokens, and Slack, Telegram, and Discord credentials stay in the service. Tool Integrations are the remaining place where a real third-party credential is handed to agent-controlled code.

Both agent-side CLIs are ours — `aai-cli` is `aai-labs/aai-cli` and `gog` is `openclaw/gogcli` — so both can be pointed somewhere other than the provider's API. That is what makes the credential removable rather than merely short-lived.

## Decision

Introduce a credential gateway and an `EgressMode` declared per provider.

- **`GATEWAY_PROXY`** — the CLI is configured with the gateway as its base URL and an `AF_GATEWAY_TOKEN` bearer. The gateway resolves the token to `(agent, provider)`, decrypts the credential, **strips the incoming gateway token**, applies the real upstream authorization, forwards, and audits. The real credential never enters the pod. This is the mode for all aai-cli providers.
- **`TOKEN_BROKER`** — the gateway holds the refresh token or service-account key and mints a short-lived, scope-narrowed upstream access token that the pod uses directly. The pod holds an expiring token but never a renewable grant. This is the mode for Google Workspace.
- **`DIRECT`** — credential materialization into the pod. Retained as the global rollback behavior and as the explicit escape hatch for a CLI whose auth cannot be redirected, so that such a case is recorded rather than bolted on as a special case.

The plugin's mode is the only provider-level routing decision. A global `CREDENTIAL_GATEWAY_ENABLED` operational switch can temporarily collapse every effective mode to `DIRECT`; there is deliberately no provider allowlist that must be kept synchronized with the plugin registry.

The gateway token is openly a credential to Agent Barn, not a disguised provider token. Revocation, scoping, and audit are all clearer when the agent's identity is ours to interpret.

Because resolution happens per request rather than at agent start, revocation applies on the next request and rotation requires no agent restart.

## Why Google brokers instead of proxying

`gogcli` accepts `GOG_ACCESS_TOKEN` as a root flag (`internal/cmd/root.go`), consumed at the single choke point every service client passes through (`internal/googleapi/client.go`) as an `oauth2.StaticTokenSource`, and checked *before* auth dependencies are required. Supplying it removes the need for the keyring, `credentials.json`, and token import entirely — with no change to gogcli.

`gogcli` exposes no base-URL or endpoint override anywhere. Proxying it would mean threading `option.WithEndpoint` through every service client and carrying that against upstream indefinitely. That permanent divergence is not worth the marginal gain of converting "≤1h scoped token in pod" into "nothing in pod."

Residual `TOKEN_BROKER` exposure is narrowed two ways: minting per-subcommand scope subsets rather than the full granted set, and using service accounts with domain-wide delegation where the customer is a Workspace org, which removes the user refresh token from the system entirely.

## Consequences

- `gog-setup.sh`, the file keyring, and the wipe-and-rebuild `GOG_HOME` machinery are deleted. The encrypted Agent Secret remains the source of truth without a per-boot pod-side reconstruction.
- Provider auth schemes become code on a provider plugin rather than gateway configuration, so schemes beyond bearer, basic, header, and query parameter — request signing, for example — need no gateway change. See [`2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md`](2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md).
- The gateway lands on the request path of every tool call. It is in the blast radius of all agent tool use, and its availability budget must match agent availability.
- Cross-host redirects become the gateway's responsibility for `GATEWAY_PROXY` providers. Responses that redirect elsewhere — Drive downloads, Sheets exports — must be followed and re-authenticated by the gateway, because NetworkPolicy blocks the pod from reaching the redirect target.
- Any CLI added later must expose a base-URL override or a direct-token seam, or it is confined to `DIRECT`.
- Third-party binaries that are not ours — `git` over HTTPS is the immediate one — need their own answer. A gateway-backed credential helper covers git; a broader population of uncontrolled binaries would need this decision revisited.

## Alternatives considered

- **Fetch-at-use dynamic secrets (Vault-style, or cloud workload identity).** Rejected as the primary design: the real credential still transits the pod, which is ineffective against an agent that can run arbitrary shell. `TOKEN_BROKER` is a deliberately scoped instance of this pattern, accepted only where full proxying would require upstream surgery.
- **A sidecar container holding the credential.** Rejected: the same pod is the same trust boundary, and the credential still crosses into the agent's process on use.
- **A tool executor exposing per-endpoint RPC.** Rejected for the general case: it discards the "run the CLI" ergonomics and forces every tool surface to be re-modelled as an API. The gateway achieves the same credential-isolation property while leaving agent-visible commands unchanged.
