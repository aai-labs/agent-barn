# Chat platforms use native runtime gateways, observed by Agent Barn

Status: Proposed
Date: 2026-09-16
Origin: maintainer decision; partially supersedes [2026-08-22-agent-barn-owned-communications-gateway](2026-08-22-agent-barn-owned-communications-gateway.md) once accepted

Slack, Discord, and then Microsoft Teams Communication Connections move back to the Agent runtime's native gateway. The runtime owns provider transport, sessions, approvals, slash commands, scheduled delivery, and progress. Agent Barn still owns the Connection record (credentials, allowlists, UI, and RBAC) and keeps Connection Journal visibility through runtime hooks. The reason is the cost of parity: driving runtimes through their HTTP APIs forced Agent Barn to rebuild, per platform, features the native gateways already ship. Examples are session resume, cron delivery to origin, BOOT.md, and approval buttons (AF-299 and AF-325, where Discord alone took three defect rounds). Every runtime upgrade also risked the image patches that made those rebuilds possible.

## Considered alternatives

- **Keep the owned gateway and continue parity work.** Each new runtime feature costs N platforms of adapter and plugin work, and the result still lags the runtime.
- **Make Agent Barn a single native channel inside each runtime.** This restores runtime features with M adapters instead of N×M. It was rejected in favour of the runtimes' own platform adapters, which already exist and are maintained upstream for the priority platforms.

## Consequences

- A Connection has a transport: `gateway` or `native`. Web Chat and Email stay on the Communications Gateway because they have no native equivalent. Telegram stays there until it is prioritised.
- Native Connections lose Postgres-authoritative at-least-once delivery, dead-letter retry, and in-place reconnect. The runtime's own delivery ledger and reconnect loop replace them. Recovery becomes an Agent restart, and credential changes require a rollout.
- Journal entries, health, and delivery status for native Connections are runtime-reported and best-effort, and they stay content-free. Mirrored Communication Deliveries are never claimable or retryable.
- Teams keeps its registered Azure messaging endpoint. The gateway verifies the Bot Framework token and relays the activity, with its authorization header, to the Agent pod over the cluster network, so no Agent pod is publicly exposed.
- Hermes is adopted first because its pinned image ships Slack, Discord, and Teams adapters with native approvals. OpenClaw follows with the `@openclaw/slack` and `@openclaw/discord` channel packages published for its pinned core, so no core upgrade is needed.

## Revisit when

- The Phase 1 spike cannot correlate native gateway hooks to per-message Journal stages or Connection health without patching the runtime.
- A native adapter cannot enforce the Connection's allowlist policy before dispatch.

## Phase 1 implementation note

The Hermes Slack spike uses a deployment-level native Platform allowlist rather than the final per-Connection transport field. When Slack is native, Agent Barn excludes it from supervised ingress, expired-lease recovery, and runtime delivery claims. Hermes owns scheduled delivery for the whole runtime: the Agent Barn scheduler capture and persisted spool drain are both disabled, including for other Platforms on that Agent.

## Phase 2 implementation note

Discord uses the same deployment-level cutoff and observer. Agent Barn adopts Hermes' native Discord authorization surface—global user, role, and channel allowlists plus Allow all users—rather than maintaining distinct guild and DM policies Hermes cannot represent. Agent Barn projects these gates directly into Hermes; the observer reports content-free Connection Journal telemetry only and does not make admission decisions.

## Phase 3 implementation note

OpenClaw uses the same deployment-level cutoff, now applied regardless of runtime. Agent start installs the official Slack and Discord plugins from npm at the core's version (OpenClaw 2026.8 grants plugin state only to recorded npm installs, not to packages loaded by path) and configures them with a `channels.slack`/`channels.discord` block projected from the Connection; tokens stay in the Secret. Discord's global gates map onto OpenClaw's wildcard guild entry. An `agentbarn-observer` plugin reports content-free message, run, and send stages from OpenClaw hooks, and the pod's health server reports channel health from the gateway's own health snapshot. OpenClaw command approvals stay off, as before.
