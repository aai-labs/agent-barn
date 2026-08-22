# Agent Barn owns communication platform delivery

Status: Accepted
Date: 2026-08-22

An Agent may communicate through zero or many Agent-owned Communication Connections, including several connections for one Communication Platform. Agent Barn ships trusted Platform Plugins and owns provider ingress, durable delivery, canonical Conversation Messages, and outbound replies through a Communications Gateway; runtimes consume one versioned internal communication protocol instead of owning Slack, Teams, Telegram, Discord, or future platform transports.

## Considered alternatives

- Keeping one Platform on each Agent prevents multi-connection Agents and leaks platform configuration through the Agent aggregate.
- Moving the existing branches behind runtime-specific factories preserves an `N platforms × M runtimes` adapter matrix and leaves communication capability constrained by each runtime.
- Dynamically installed third-party plugins add package trust, migration, frontend loading, and compatibility problems that the early product does not need. Platform Plugins therefore ship in the reviewed Agent Barn release and use explicit code-owned registries.

## Consequences

Communication Connections are Agent subordinate resources governed by Agent Access Permissions. Connection credentials are distinct from Agent Secrets used for tool Integrations. Agent lifecycle and connection health remain separate, and one failed connection may degrade communication health without changing a running Agent's lifecycle state.

Inbound and outbound work uses durable, at-least-once Communication Deliveries. Provider message identity supplies deduplication, and a runtime reply is bound to the Connection and conversation that originated its source delivery. The gateway and Agent runtimes communicate through a versioned, runtime-neutral protocol.
