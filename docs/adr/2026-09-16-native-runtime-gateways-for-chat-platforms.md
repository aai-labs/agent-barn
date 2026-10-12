# Chat platforms use native runtime gateways, observed by Agent Barn

Status: Accepted
Date: 2026-09-16
Origin: maintainer decision; partially supersedes [2026-08-22-agent-barn-owned-communications-gateway](2026-08-22-agent-barn-owned-communications-gateway.md)

Slack, Discord, Telegram, and Microsoft Teams Communication Connections move back to the Agent runtime's native gateway. The runtime owns provider transport, sessions, approvals, slash commands, scheduled delivery, and progress. Agent Barn still owns the Connection record (credentials, allowlists, UI, and RBAC) and keeps Connection Journal visibility through runtime hooks. The reason is the cost of parity: driving runtimes through their HTTP APIs forced Agent Barn to rebuild, per platform, features the native gateways already ship. Examples are session resume, cron delivery to origin, BOOT.md, and approval buttons (AF-299 and AF-325, where Discord alone took three defect rounds). Every runtime upgrade also risked the image patches that made those rebuilds possible.

## Considered alternatives

- **Keep the owned gateway and continue parity work.** Each new runtime feature costs N platforms of adapter and plugin work, and the result still lags the runtime.
- **Make Agent Barn a single native channel inside each runtime.** This restores runtime features with M adapters instead of N×M. It was rejected in favour of the runtimes' own platform adapters, which already exist and are maintained upstream for the priority platforms.

## Consequences

- Transport ownership is code-owned by the shipped Platform definition, not selected per Connection or by a deployment allowlist. All four chat Platforms use native transport on both Hermes and OpenClaw, with no gateway fallback. Web Chat and Email retain the Communications Gateway because they have no native equivalent.
- Native Connections lose Postgres-authoritative at-least-once delivery, dead-letter retry, and in-place reconnect. The runtime's own delivery ledger and reconnect loop replace them. Recovery becomes an Agent restart, and credential changes require a rollout.
- Native Connection Journal entries and health are runtime-reported, best-effort, and content-free. The authenticated runtime observer may separately mirror normalized transcript messages into existing conversation history, where Agent-conversation authorization and retention apply. Observation creates no Communication Delivery rows and cannot become a claim or retry path.
- Teams keeps its registered Azure messaging endpoint. The product API verifies the Bot Framework token, applies Connection admission policy, and relays the activity with its authorization header to the Agent pod over the cluster network, so no Agent pod is publicly exposed.
- Agent Barn continues to own Connection configuration, credentials, authorization, and shipped Platform Plugins. Native channel packages and runtime observers remain supported independently of the retired gateway transports and custom messaging bridge.

The [runtime architecture](../architecture/runtime-and-deployment.md#platform-plugin-boundary) owns the current transport, policy projection, observation, and recovery contract. The [Communications change log](../features/communications/CHANGELOG.md) records the Hermes-first adoption, OpenClaw adoption, and subsequent fallback retirement. The [rollout runbook](../guidelines/operations.md#native-runtime-gateway-rollout) owns compatibility cutoffs and retained historical state.

## Revisit when

- Native runtime hooks cannot provide required Connection Journal correlation or health without patching the runtime.
- A native adapter cannot enforce the Connection's admission policy before dispatch.

## Agent Barn Telegram (AF-367)

Agent Barn Telegram lets Organizations, initially trial clients, use one Telegram bot owned by Agent Barn instead of bringing their own. It stays on the runtimes' native Telegram adapters, consistent with this decision, rather than reviving gateway-owned delivery. The shared token must never reach an Agent, so the native adapters run behind two Agent Barn components in the Communications process. The poller is the bot's single consumer and forwards each linked user's raw updates to that Agent's private webhook, authenticated by a secret derived from the Connection's own runtime secret, as the Teams relay does for Bot Framework. The Bot API proxy is each runtime's API root (Hermes `extra.base_url`, OpenClaw `apiRoot`) and takes a per-Connection stand-in token derived from the same secret. It answers bot-wide calls such as `setWebhook` and `setMyCommands` locally, forwards chat calls only for users linked to that Connection, and rate-limits per Organization. People link their own Telegram account through a one-time deep link; a Telegram user reaches at most one Agent at a time.
